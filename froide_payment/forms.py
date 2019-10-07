import json
import uuid

from django import forms
from django.utils.translation import ugettext_lazy as _

import stripe

from payments import FraudStatus
from payments.forms import PaymentForm as BasePaymentForm

from localflavor.generic.forms import IBANFormField

from .models import PaymentStatus


class SourcePaymentForm(BasePaymentForm):
    stripe_source = forms.CharField(widget=forms.HiddenInput)

    def _handle_potentially_fraudulent_charge(self, charge, commit=True):
        fraud_details = charge['fraud_details']
        if fraud_details.get('stripe_report', None) == 'fraudulent':
            self.payment.change_fraud_status(FraudStatus.REJECT, commit=commit)
        else:
            self.payment.change_fraud_status(FraudStatus.ACCEPT, commit=commit)

    def clean(self):
        data = self.cleaned_data

        if not self.errors:
            if self.payment.transaction_id:
                msg = _('This payment has already been processed.')
                self.add_error(None, msg)

        return data

    def save(self):
        try:
            self.charge = stripe.Charge.create(
                amount=int(self.payment.total * 100),
                currency=self.payment.currency,
                source=self.cleaned_data['stripe_source'],
                description='%s %s' % (
                    self.payment.billing_last_name,
                    self.payment.billing_first_name)
            )
        except stripe.error.StripeError as e:
            charge_id = e.json_body['error']['charge']
            self.charge = stripe.Charge.retrieve(charge_id)
            # Checking if the charge was fraudulent
            self._handle_potentially_fraudulent_charge(
                self.charge, commit=False)

            self.payment.change_status(PaymentStatus.REJECTED, str(e))
            return

        self.payment.transaction_id = self.charge.id
        self.payment.attrs.charge = json.dumps(self.charge)
        # self.payment.change_status(PaymentStatus.PREAUTH)
        self.payment.save()

        # Make sure we store the info of the charge being marked as fraudulent
        self._handle_potentially_fraudulent_charge(self.charge)


class LastschriftPaymentForm(BasePaymentForm):
    iban = IBANFormField(
        label=_('Your IBAN'),
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'pattern': (
                    r"^[A-Z]{2}\d{2}[ ]\d{4}[ ]\d{4}[ ]\d{4}[ ]\d{4}[ ]*"
                    r"\d{0,2}|[A-Z]{2}\d{20,22}$"
                ),
                'placeholder': _('IBAN'),
                'title': _(
                    'The IBAN has 20-22 digits and starts with two letters.'
                )
            }
        )
    )
    terms = forms.BooleanField(
        required=True,
        label='Lastschrift einziehen',
        help_text=(
            "Ich ermächtige (A) Open Knowledge Foundation Deutschland e.V., "
            "Zahlungen von meinem Konto mittels Lastschrift einzuziehen. "
            "Zugleich (B) weise ich mein Kreditinstitut an, die von "
            "Open Knowledge Foundation auf mein Konto gezogenen Lastschriften "
            "einzulösen. Hinweis: Ich kann innerhalb von acht Wochen, "
            "beginnend mit dem Belastungsdatum, die Erstattung des belasteten "
            "Betrages verlangen. Es gelten dabei die mit meinem "
            "Kreditinstitut vereinbarten Bedingungen."
        ),
        error_messages={
            'required': _(
                'Sie müssen den Bedingungen der Lastschrift zustimmen.'
            )},
    )

    def save(self):
        self.payment.attrs.iban = self.cleaned_data['iban']
        self.payment.transaction_id = str(uuid.uuid4())
        self.payment.change_status(PaymentStatus.PENDING)  # Calls .save()
