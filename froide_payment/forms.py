import json
import uuid

from django import forms
from django.utils.translation import gettext_lazy as _

from django_countries.fields import CountryField
from localflavor.generic.countries.sepa import IBAN_SEPA_COUNTRIES
from localflavor.generic.forms import IBANFormField
from payments.core import provider_factory
from payments.forms import PaymentForm as BasePaymentForm

from .models import Customer, Order, PaymentStatus, Subscription
from .signals import subscription_created


class LastschriftPaymentForm(BasePaymentForm):
    owner_name = forms.CharField(
        label=_("Account owner"),
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": _("Account owner"),
            }
        ),
    )
    iban = IBANFormField(
        label=_("Your IBAN"),
        required=True,
        include_countries=IBAN_SEPA_COUNTRIES,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "pattern": (
                    # 36 len includes possible spaces
                    r"^[A-Z]{2}\d{2}[ ]*[ A-Za-z\d]{11,36}"
                ),
                "placeholder": _("e.g. DE12..."),
                "title": _(
                    "The IBAN starts with two letters and then two numbers. "
                    "SEPA countries only."
                ),
            }
        ),
    )
    terms = forms.BooleanField(
        required=True,
        label="Lastschrift einziehen",
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
            "required": _("Sie müssen den Bedingungen der Lastschrift zustimmen.")
        },
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner_name"].initial = self.payment.order.get_full_name()
        try:
            self.fields["iban"].initial = self.payment.attrs.iban
            self.fields["owner_name"].initial = self.payment.attrs.owner
        except (KeyError, AttributeError):
            pass

    def save(self):
        self.payment.attrs.iban = self.cleaned_data["iban"]
        self.payment.attrs.owner = self.cleaned_data["owner_name"]
        order = self.payment.order
        if order.is_recurring:
            subscription = order.subscription
            customer = subscription.customer
            iban_data = json.dumps(
                {
                    "owner": self.cleaned_data["owner_name"],
                    "iban": self.cleaned_data["iban"],
                }
            )
            customer.custom_data = iban_data
            customer.save()
        return self.finalize_payment()

    def finalize_payment(self):
        self.payment.transaction_id = str(uuid.uuid4())
        self.payment.change_status(PaymentStatus.PENDING)
        self.payment.save()


class SEPAPaymentForm(LastschriftPaymentForm):
    terms = None  # Handled client side
    iban_address_required = (
        "AD",
        "PF",
        "TF",
        "GI",
        "GB",
        "GG",
        "VA",
        "IM",
        "JE",
        "MC",
        "NC",
        "BL",
        "PM",
        "SM",
        "CH",
        "WF",
    )

    address = forms.CharField(
        label=_("address"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": _("Address"),
            }
        ),
    )

    postcode = forms.CharField(
        max_length=20,
        label=_("Postcode"),
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": _("Postcode"), "class": "form-control"}
        ),
    )
    city = forms.CharField(
        max_length=255,
        label=_("City"),
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": _("City"), "class": "form-control"}
        ),
    )

    country = CountryField().formfield(
        label=_("Country"),
        required=False,
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    SEPA_MANDATE = _(
        "By providing your payment information and confirming this payment, you "
        "authorise (A) Open Knowledge Foundation Deutschland e.V. and Stripe, our "
        "payment service provider and/or PPRO, its local service provider, to send "
        "instructions to your bank to debit your account and (B) your bank to debit "
        "your account in accordance with those instructions. As part of your rights, "
        "you are entitled to a refund from your bank under the terms and conditions of "
        "your agreement with your bank. A refund must be claimed within 8 weeks "
        "starting from the date on which your account was debited. Your rights are "
        "explained in a statement that you can obtain from your bank. You agree to "
        "receive notifications for future debits up to 2 days before they occur."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.iban_address_required_regex = "|".join(self.iban_address_required)
        order = self.payment.order
        self.fields["address"].initial = order.street_address_1
        self.fields["postcode"].initial = order.postcode
        self.fields["city"].initial = order.city
        self.fields["country"].initial = order.country

    def clean(self):
        if "iban" not in self.cleaned_data:
            return self.cleaned_data
        address = None
        if self.cleaned_data["iban"][:2] in self.iban_address_required:
            address = {
                "line1": self.cleaned_data["address"],
                "city": self.cleaned_data["city"],
                "postal_code": self.cleaned_data["postcode"],
                "country": self.cleaned_data["country"],
            }
        try:
            self.payment_method = self.provider.create_payment_method(
                self.cleaned_data["iban"],
                self.cleaned_data["owner_name"],
                self.payment.billing_email,
                address=address,
            )
        except ValueError as e:
            if e.args[0] == "invalid_bank_account_iban":
                raise forms.ValidationError(
                    _("The provided IBAN seems invalid."), code=e.args[0]
                )
            elif e.args[0] == "invalid_owner_name":
                raise forms.ValidationError(
                    _(
                        "The provided owner name seems invalid (at least "
                        "3 characters required)."
                    ),
                    code=e.args[0],
                )
            elif e.args[0] == "payment_method_not_available":
                raise forms.ValidationError(
                    _("This payment method is currently unavailable."), code=e.args[0]
                )
            else:
                raise forms.ValidationError(
                    _(
                        "An error occurred verifying your information with "
                        "our payment provider. Please try again."
                    ),
                    code=e.args[0],
                )
        return self.cleaned_data

    def finalize_payment(self):
        pass


class StartPaymentMixin:
    def get_payment_metadata(self, data):
        raise NotImplementedError

    def create_customer(self, data):
        address_lines = data["address"].splitlines() or [""]
        defaults = dict(
            first_name=data["first_name"],
            last_name=data["last_name"],
            street_address_1=address_lines[0],
            street_address_2="\n".join(address_lines[1:]),
            city=data["city"],
            postcode=data["postcode"],
            country=data["country"],
            user_email=data["email"],
            provider=data["payment_method"],
        )
        customer = None
        if self.user is not None:
            customers = Customer.objects.filter(
                user=self.user, provider=data["payment_method"]
            )
            if len(customers) > 0:
                customer = customers[0]
                Customer.objects.filter(id=customer.id).update(**defaults)
        if customer is None:
            customer = Customer.objects.create(**defaults)
        return customer

    def create_plan(self, data):
        metadata = self.get_payment_metadata(data)
        provider = provider_factory(data["payment_method"])
        plan = provider.get_or_create_plan(
            metadata["plan_name"],
            metadata["category"],
            data["amount"],
            data["interval"],
        )
        return plan

    def create_subscription(self, data):
        customer = self.create_customer(data)
        plan = self.create_plan(data)
        subscription = Subscription.objects.create(
            active=False, customer=customer, plan=plan
        )
        subscription_created.send(sender=subscription)
        return subscription

    def create_single_order(self, data):
        metadata = self.get_payment_metadata(data)
        address_lines = data["address"].splitlines() or [""]
        order = Order.objects.create(
            user=self.user,
            first_name=data["first_name"],
            last_name=data["last_name"],
            street_address_1=address_lines[0],
            street_address_2="\n".join(address_lines[1:]),
            city=data["city"],
            postcode=data["postcode"],
            country=data["country"],
            user_email=data["email"],
            total_net=data["amount"],
            total_gross=data["amount"],
            is_donation=data.get("is_donation", True),
            description=metadata["description"],
            kind=metadata["kind"],
        )
        return order

    def create_order(self, data):
        if data["interval"] > 0:
            metadata = self.get_payment_metadata(data)
            subscription = self.create_subscription(data)
            order = subscription.create_order(
                kind=metadata["kind"],
                description=metadata["description"],
                is_donation=data.get("is_donation", True),
            )
        else:
            order = self.create_single_order(data)
        return order
