import json

from django import forms
from django.utils.translation import ugettext_lazy as _

import stripe

from payments import PaymentStatus, FraudStatus
from payments.forms import PaymentForm as BasePaymentForm


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
