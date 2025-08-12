import json
import uuid
from datetime import timedelta

from django import forms
from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField
from froide.helper.email_sending import mail_registry
from froide.helper.widgets import BootstrapRadioSelect
from localflavor.generic.countries.sepa import IBAN_SEPA_COUNTRIES
from localflavor.generic.forms import IBANFormField
from payments.core import provider_factory
from payments.forms import PaymentForm as BasePaymentForm

from froide_payment.widgets import PriceInput

from .models import Customer, Order, PaymentStatus, Subscription
from .signals import subscription_created
from .utils import interval_description

modify_subscription_confirmation = mail_registry.register(
    "froide_payment/email/modify_subscription",
    ("customer", "subscription", "changes", "data", "action_url"),
)


class IBANMixin(forms.Form):
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
                    r"^[A-Za-z]{2}\d{2}[ ]*[ A-Za-z\d]{11,36}"
                ),
                "placeholder": _("e.g. DE12..."),
                "title": _(
                    "The IBAN starts with two letters and then two numbers. "
                    "SEPA countries only."
                ),
            }
        ),
    )


class LastschriftPaymentForm(IBANMixin, BasePaymentForm):
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
        error_messages={"required": _("You have to accept the terms of direct debit.")},
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
        self.payment.change_status_and_save(PaymentStatus.PENDING)


class SEPAMixin(forms.Form):
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
    iban_address_required_regex = "|".join(iban_address_required)

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
        "By providing your payment information and confirming this payment, you authorise (A) Open Knowledge Foundation Deutschland e.V. and Stripe, our payment service provider, to send instructions to your bank to debit your account and (B) your bank to debit your account in accordance with those instructions. As part of your rights, you are entitled to a refund from your bank under the terms and conditions of your agreement with your bank. A refund must be claimed within 8 weeks starting from the date on which your account was debited. Your rights are explained in a statement that you can obtain from your bank. You agree to receive notifications for future debits up to 2 days before they occur."
    )

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
                self.email,
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


class SEPAPaymentForm(SEPAMixin, LastschriftPaymentForm):
    terms = None  # Handled client side

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        order = self.payment.order
        self.email = self.payment.billing_email
        self.fields["address"].initial = order.street_address_1
        self.fields["postcode"].initial = order.postcode
        self.fields["city"].initial = order.city
        self.fields["country"].initial = order.country

    def finalize_payment(self):
        pass


class SEPASubscriptionChangeForm(IBANMixin, SEPAMixin, forms.Form):
    class Media:
        js = {
            "all": ["payment.js"],
        }

    def __init__(self, *args, **kwargs):
        self.subscription = kwargs.pop("subscription")
        self.provider = kwargs.pop("provider")
        self.current_method_label = kwargs.pop("current_method_label", None)
        self.provider.get_payment_method_info(self.subscription)
        self.public_key = self.provider.public_key
        self.stripe_country = getattr(settings, "STRIPE_COUNTRY", "DE")
        super().__init__(*args, **kwargs)
        customer = self.subscription.customer
        self.order = self.subscription.get_last_order()
        self.email = customer.user_email
        self.fields["owner_name"].initial = customer.get_full_name()
        self.fields["address"].initial = customer.street_address_1
        self.fields["postcode"].initial = customer.postcode
        self.fields["city"].initial = customer.city
        self.fields["country"].initial = customer.country


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


class ModifySubscriptionForm(forms.Form):
    amount = forms.DecimalField(
        localize=True,
        required=True,
        min_value=5,
        max_digits=19,
        decimal_places=2,
        label=_("Donation amount:"),
        widget=PriceInput,
    )
    interval = forms.TypedChoiceField(
        choices=[
            ("1", _("monthly")),
            ("3", _("quarterly")),
            ("12", _("yearly")),
        ],
        coerce=int,
        empty_value=None,
        required=True,
        label=_("Frequency"),
        widget=BootstrapRadioSelect,
    )
    next_date = forms.DateField(
        label=_("Next payment date"),
        localize=True,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        self.subscription = kwargs.pop("subscription")
        super().__init__(*args, **kwargs)
        self.fields["amount"].initial = self.subscription.plan.amount
        self.fields["interval"].initial = self.subscription.plan.interval
        provider = self.subscription.get_provider()
        modify_info = provider.get_modify_info(self.subscription)
        if not modify_info.can_schedule:
            del self.fields["next_date"]
            return
        min_date = timezone.now().date() + timedelta(days=1)
        self.fields["next_date"].initial = (
            self.subscription.get_next_date() or min_date
        ).strftime("%Y-%m-%d")
        self.fields["next_date"].widget.attrs["min"] = min_date.strftime("%Y-%m-%d")

    def clean_next_date(self):
        next_date = self.cleaned_data["next_date"]
        if next_date < timezone.now().date() + timedelta(days=1):
            raise forms.ValidationError(_("Date must be in the future"))
        return next_date

    def _get_signer(self):
        return signing.TimestampSigner(salt="modify-subscription")

    def send_confirmation_email(self):
        assert self.is_valid()
        signer = self._get_signer()
        # Send and sign flattened POST data so it serializes
        data = self.data.dict()
        data.pop("csrfmiddlewaretoken", None)
        data["token"] = str(self.subscription.token)
        value = signer.sign_object(data)
        url = settings.SITE_URL + (
            reverse(
                "froide_payment:subscription-modify-confirm",
                kwargs={"token": self.subscription.token},
            )
            + "?code="
            + value
        )
        changes = {}
        if self.subscription.plan.amount != self.cleaned_data["amount"]:
            changes["amount"] = {
                "old": self.subscription.plan.amount,
                "new": self.cleaned_data["amount"],
            }
        if self.subscription.plan.interval != self.cleaned_data["interval"]:
            changes["interval"] = {
                "old": interval_description(self.subscription.plan.interval),
                "new": interval_description(self.cleaned_data["interval"]),
            }
        modify_subscription_confirmation.send(
            email=self.subscription.customer.user_email,
            subject=_("Please confirm your subscription modification"),
            context={
                "customer": self.subscription.customer,
                "subscription": self.subscription,
                "changes": changes,
                "data": self.cleaned_data,
                "action_url": url,
            },
        )

    def get_form_data_from_code(self, code):
        signer = self._get_signer()
        # Allow an hour for the code to be valid
        try:
            data = signer.unsign_object(code, max_age=60 * 60)
        except signing.SignatureExpired:
            raise ValueError(_("Confirmation link has expired."))
        except signing.BadSignature:
            raise ValueError(_("Invalid confirmation link."))
        token = data.pop("token", None)
        if token != str(self.subscription.token):
            raise ValueError(_("Invalid confirmation link."))
        return data

    def save(self):
        provider = self.subscription.get_provider()
        return provider.modify_subscription(
            self.subscription,
            **self.cleaned_data,
        )
