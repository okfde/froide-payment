import uuid
import json

from django.conf import settings
from django.db import models
from django.apps import apps
from django.urls import reverse
from django.utils.translation import pgettext_lazy, ugettext_lazy as _
from django.utils import timezone

from django_countries.fields import CountryField
from django_prices.models import MoneyField, TaxedMoneyField
from prices import Money, TaxedMoney
from dateutil.relativedelta import relativedelta

from payments import PurchasedItem, PaymentStatus as BasePaymentStatus
from payments.models import BasePayment


CHECKOUT_PAYMENT_CHOICES = [
    ('default', _('Dummy')),
    ('creditcard', _('Credit Card')),
    ('sepa', _('SEPA Debit')),
    ('lastschrift', _('SEPA Lastschrift')),
    ('sofort', _('SOFORT Überweisung')),
    ('paypal', _('Paypal')),
]

CHECKOUT_PAYMENT_CHOICES_DICT = dict(CHECKOUT_PAYMENT_CHOICES)

PAYMENT_METHODS = [
    variant for variant in CHECKOUT_PAYMENT_CHOICES
    if variant[0] in settings.PAYMENT_VARIANTS
]

ZERO_MONEY = Money(0, settings.DEFAULT_CURRENCY)
ZERO_TAXED_MONEY = TaxedMoney(net=ZERO_MONEY, gross=ZERO_MONEY)

MONTHLY_INTERVALS = (
    (1, _(u'monthly')),
    (3, _(u'quarterly')),
    (6, _(u'semiannually')),
    (12, _(u'annually')),
)


class Plan(models.Model):
    name = models.CharField(max_length=256)
    slug = models.SlugField()
    category = models.CharField(max_length=256, blank=True)
    description = models.TextField(blank=True)

    created = models.DateTimeField(
        default=timezone.now, editable=False)
    amount = MoneyField(
        currency=settings.DEFAULT_CURRENCY, max_digits=12,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0)
    interval = models.PositiveSmallIntegerField(
        verbose_name=_('interval'),
        choices=MONTHLY_INTERVALS, null=True, blank=True
    )

    remote_reference = models.CharField(max_length=256, blank=True)

    def __str__(self):
        return self.name


class Customer(models.Model):
    created = models.DateTimeField(
        default=timezone.now, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True,
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

    remote_reference = models.CharField(max_length=256, blank=True)

    custom_data = models.TextField()

    def __str__(self):
        return self.user_email

    @property
    def data(self):
        try:
            return json.loads(self.custom_data or '{}')
        except ValueError:
            return {}


class Subscription(models.Model):
    active = models.BooleanField(default=False)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.CASCADE
    )

    created = models.DateTimeField(
        default=timezone.now, editable=False)

    last_date = models.DateTimeField(
        null=True, blank=True)
    next_date = models.DateTimeField(
        null=True, blank=True)

    remote_reference = models.CharField(max_length=256, blank=True)
    token = models.UUIDField(default=uuid.uuid4, db_index=True)

    def __str__(self):
        return self.customer

    def get_next_date(self):
        timestamp = self.last_date
        if self.last_date is None:
            timestamp = self.created
        return timestamp + relativedelta(months=self.plan.interval)

    def create_order(self, kind='', is_donation=False):
        now = timezone.now()
        if self.next_date and self.next_date > now.date():
            raise ValueError
        customer = self.customer
        order = Order.objects.create(
            customer=customer,
            subscription=self,
            user=customer.user,
            first_name=customer.first_name,
            last_name=customer.last_name,
            street_address_1=customer.street_address_1,
            street_address_2=customer.street_address_2,
            city=customer.city,
            postcode=customer.postcode,
            country=customer.country,
            user_email=customer.user_email,
            total_net=self.plan.amount,
            total_gross=self.plan.amount,
            is_donation=is_donation,
            kind=kind,
            description=self.plan.name
        )
        return order


class Order(models.Model):
    created = models.DateTimeField(
        default=timezone.now, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True,
        related_name='invoices',
        on_delete=models.SET_NULL)
    customer = models.ForeignKey(
        Customer, blank=True, null=True,
        on_delete=models.SET_NULL
    )
    subscription = models.ForeignKey(
        Subscription, blank=True, null=True,
        on_delete=models.SET_NULL
    )

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
    def email(self):
        return self.user_email

    @property
    def address(self):
        return '\n'.join(x for x in [
            self.street_address_1,
            self.street_address_2,
            '{} {}'.format(self.postcode, self.city),
            self.country.name
        ] if x)

    def get_user_or_order(self):
        if self.user:
            return self.user
        return self

    def get_full_name(self):
        return '{} {}'.format(self.first_name, self.last_name).strip()

    def is_fully_paid(self):
        total_paid = sum([
            payment.get_captured_amount() for payment in
            self.payments.filter(status=PaymentStatus.CONFIRMED)],
            ZERO_TAXED_MONEY
        )
        return total_paid.gross >= self.total.gross

    def get_absolute_url(self):
        return reverse('froide_payment:order-detail', kwargs={
            'token': self.token
        })

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
            if self.subscription:
                return model.objects.get(subscription=self.subscription)
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


class PaymentStatus(BasePaymentStatus):
    PENDING = 'pending'

    CHOICES = BasePaymentStatus.CHOICES + [
        (PENDING, pgettext_lazy('payment status', 'Confirmation pending')),
    ]


class Payment(BasePayment):
    status = models.CharField(
        max_length=10, choices=PaymentStatus.CHOICES,
        default=PaymentStatus.WAITING)
    order = models.ForeignKey(
        Order, related_name='payments',
        on_delete=models.PROTECT
    )

    class Meta:
        ordering = ('-modified',)

    STATUS_COLORS = {
        PaymentStatus.WAITING: 'secondary',
        PaymentStatus.PREAUTH: 'light',
        PaymentStatus.PENDING: 'secondary',
        PaymentStatus.CONFIRMED: 'success',
        PaymentStatus.REJECTED: 'danger',
        PaymentStatus.REFUNDED: 'warning',
        PaymentStatus.ERROR: 'danger',
        PaymentStatus.INPUT: 'light',
    }

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

    def get_variant_display(self):
        return CHECKOUT_PAYMENT_CHOICES_DICT.get(self.variant, '')

    @property
    def status_color(self):
        return self.STATUS_COLORS[self.status]
