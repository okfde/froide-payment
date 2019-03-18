import uuid

from django.conf import settings
from django.db import models
from django.apps import apps
from django.utils.translation import ugettext_lazy as _
from django.utils import timezone

from django_countries.fields import CountryField
from django_prices.models import MoneyField, TaxedMoneyField
from prices import Money, TaxedMoney

from payments import PurchasedItem, PaymentStatus
from payments.models import BasePayment


CHECKOUT_PAYMENT_CHOICES = [
    ('creditcard', _('Credit Card')),
    ('sepa', _('SEPA Debit')),
]

PAYMENT_METHODS = [
    variant for variant in CHECKOUT_PAYMENT_CHOICES
    if variant[0] in settings.PAYMENT_VARIANTS
]

ZERO_MONEY = Money(0, settings.DEFAULT_CURRENCY)
ZERO_TAXED_MONEY = TaxedMoney(net=ZERO_MONEY, gross=ZERO_MONEY)


class Order(models.Model):
    created = models.DateTimeField(
        default=timezone.now, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True,
        related_name='invoices',
        on_delete=models.SET_NULL)

    first_name = models.CharField(max_length=256, blank=True)
    last_name = models.CharField(max_length=256, blank=True)
    company_name = models.CharField(max_length=256, blank=True)
    street_address_1 = models.CharField(max_length=256, blank=True)
    street_address_2 = models.CharField(max_length=256, blank=True)
    city = models.CharField(max_length=256, blank=True)
    postcode = models.CharField(max_length=20, blank=True)
    country = CountryField()

    user_email = models.EmailField(blank=True, default='')

    total_net = MoneyField(
        currency=settings.DEFAULT_CURRENCY, max_digits=12,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0)
    total_gross = MoneyField(
        currency=settings.DEFAULT_CURRENCY, max_digits=12,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0)
    total = TaxedMoneyField(net_field='total_net', gross_field='total_gross')

    is_donation = models.BooleanField(default=False)
    description = models.CharField(max_length=255, blank=True)
    customer_note = models.TextField(blank=True, default='')
    kind = models.CharField(max_length=255, default='', blank=True)

    token = models.UUIDField(default=uuid.uuid4, db_index=True)

    def __str__(self):
        return self.description

    @property
    def currency(self):
        return settings.DEFAULT_CURRENCY

    @property
    def amount(self):
        return self.total.gross.amount

    @property
    def amount_cents(self):
        return int(self.total.gross.amount * 100)

    @property
    def address(self):
        return '\n'.join(x for x in [
            self.street_address_1,
            self.street_address_2,
            '{} {}'.format(self.postcode, self.city),
            self.country.name
        ] if x)

    def is_fully_paid(self):
        total_paid = sum([
            payment.get_captured_amount() for payment in
            self.payments.filter(status=PaymentStatus.CONFIRMED)],
            ZERO_TAXED_MONEY
        )
        return total_paid.gross >= self.total.gross

    def get_failure_url(self):
        obj = self.get_domain_object()
        if obj is None:
            return '/'
        return obj.get_failure_url()

    def get_success_url(self):
        obj = self.get_domain_object()
        if obj is None:
            return '/'
        return obj.get_success_url()

    def get_domain_object(self):
        model = self.get_domain_model()
        if model is None:
            return None
        try:
            return model.objects.get(order=self)
        except model.DoesNotExist:
            return None

    def get_domain_model(self):
        if not self.kind:
            return None
        try:
            return apps.get_model(self.kind)
        except LookupError:
            return None


class Payment(BasePayment):
    order = models.ForeignKey(
        Order, related_name='payments',
        on_delete=models.PROTECT
    )

    def get_captured_amount(self):
        return Money(
            self.captured_amount, self.currency or settings.DEFAULT_CURRENCY
        )

    def get_failure_url(self):
        return self.order.get_failure_url()

    def get_success_url(self):
        return self.order.get_success_url()

    def get_purchased_items(self):
        order = self.order
        yield PurchasedItem(
            name=str(order.description),
            quantity=1,
            price=order.total_gross.amount,
            currency=order.total_gross.currency,
            sku=order.id
        )
