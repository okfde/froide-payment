from collections import defaultdict
import json
import uuid

from django.conf import settings
from django.db import models, transaction
from django.apps import apps
from django.urls import reverse
from django.utils.translation import pgettext_lazy, gettext_lazy as _
from django.utils import timezone

from django_countries.fields import CountryField
from django_prices.models import TaxedMoneyField
from prices import Money, TaxedMoney
from dateutil.relativedelta import relativedelta

from payments import PurchasedItem, PaymentStatus as BasePaymentStatus
from payments.core import provider_factory
from payments.models import BasePayment

from .signals import subscription_canceled
from .utils import (
    get_payment_defaults, interval_description,
    order_service_description
)


CHECKOUT_PAYMENT_CHOICES = [
    ('default', _('Dummy')),
    ('creditcard', _('Credit Card')),
    ('sepa', _('SEPA-Lastschrift')),
    ('lastschrift', _('Lastschrift')),
    ('sofort', _('SOFORT Überweisung')),
    ('paypal', _('Paypal')),
    ('banktransfer', _('Bank transfer')),
]

CHECKOUT_PAYMENT_CHOICES_DICT = dict(CHECKOUT_PAYMENT_CHOICES)

PAYMENT_METHODS = [
    variant for variant in CHECKOUT_PAYMENT_CHOICES
    if variant[0] in settings.PAYMENT_VARIANTS
]

ZERO_MONEY = Money(0, settings.DEFAULT_CURRENCY)
ZERO_TAXED_MONEY = TaxedMoney(net=ZERO_MONEY, gross=ZERO_MONEY)

MONTHLY_INTERVALS = (
    (1, _('monthly')),
    (3, _('quarterly')),
    (6, _('semiannually')),
    (12, _('annually')),
)


class Product(models.Model):
    name = models.CharField(max_length=256)

    category = models.CharField(max_length=256, blank=True)

    provider = models.CharField(max_length=256, blank=True)
    remote_reference = models.CharField(max_length=256, blank=True)

    def __str__(self):
        return self.name


class Plan(models.Model):
    name = models.CharField(max_length=256)
    slug = models.SlugField()
    category = models.CharField(max_length=256, blank=True)
    description = models.TextField(blank=True)

    created = models.DateTimeField(
        default=timezone.now, editable=False)
    amount = models.DecimalField(
        max_digits=12, decimal_places=settings.DEFAULT_DECIMAL_PLACES,
        default=0
    )
    interval = models.PositiveSmallIntegerField(
        verbose_name=_('interval'),
        choices=MONTHLY_INTERVALS, null=True, blank=True
    )
    amount_year = models.DecimalField(
        max_digits=12,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0
    )

    remote_reference = models.CharField(max_length=256, blank=True)
    provider = models.CharField(max_length=256, blank=True)
    product = models.ForeignKey(
        Product, null=True, blank=True,
        on_delete=models.SET_NULL
    )

    def __str__(self):
        return '{} via {}'.format(self.name, self.provider)

    def get_interval_description(self):
        return interval_description(self.interval)


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
    country = CountryField(blank=True)

    user_email = models.EmailField(blank=True, default='')

    provider = models.CharField(max_length=256, blank=True)
    remote_reference = models.CharField(max_length=256, blank=True)

    custom_data = models.TextField(blank=True)

    class Meta:
        ordering = ('-created',)

    def __str__(self):
        return self.user_email

    def get_full_name(self):
        return '{} {}'.format(self.first_name, self.last_name).strip()

    @property
    def data(self):
        try:
            return json.loads(self.custom_data or '{}')
        except ValueError:
            return {}


class Subscription(models.Model):
    active = models.BooleanField(default=False)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE,
        related_name='subscriptions'
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

    canceled = models.DateTimeField(
        null=True, blank=True)

    remote_reference = models.CharField(max_length=256, blank=True)
    token = models.UUIDField(default=uuid.uuid4, db_index=True)

    def __str__(self):
        return str(self.customer)

    def get_absolute_url(self):
        return reverse('froide_payment:subscription-detail', kwargs={
            'token': str(self.token)
        })

    def get_next_date(self):
        timestamp = self.last_date
        if self.last_date is None:
            timestamp = self.created
        return timestamp + relativedelta(months=self.plan.interval)

    def get_last_order(self):
        return self.orders.all().order_by(
            '-service_end'
        ).first()

    def get_first_order(self):
        return self.orders.all().order_by(
            'service_end'
        ).first()

    def attach_order_info(self, remote_reference='', **extra):
        order = self.get_last_order()
        if not order:
            return
        order.remote_reference = remote_reference
        order.save()

    def create_recurring_order(self, force=False, now=None,
                               remote_reference=None):
        from .utils import create_recurring_order

        return create_recurring_order(
            self, force=force, now=now, remote_reference=remote_reference
        )

    def create_order(self, kind='', description=None, is_donation=True,
                     remote_reference=''):
        now = timezone.now()

        last_order = self.get_last_order()
        service_start = None
        if last_order:
            service_start = last_order.service_end
            if not kind:
                kind = last_order.kind
        if not service_start:
            service_start = now
        service_end = service_start + relativedelta(months=self.plan.interval)

        if description is None:
            description = self.plan.name
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
            description=description,
            service_start=service_start,
            service_end=service_end,
            remote_reference=remote_reference
        )
        return order

    def get_provider(self):
        return provider_factory(self.plan.provider)

    def get_cancel_info(self):
        provider = self.get_provider()
        return provider.get_cancel_info(self)

    def cancel(self):
        provider = self.get_provider()
        success = provider.cancel_subscription(self)
        self.active = False
        self.canceled = timezone.now()
        self.save()
        subscription_canceled.send(sender=self)
        return success


class Order(models.Model):
    created = models.DateTimeField(
        default=timezone.now)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True,
        related_name='invoices',
        on_delete=models.SET_NULL)
    customer = models.ForeignKey(
        Customer, blank=True, null=True,
        on_delete=models.SET_NULL,
        related_name='orders'
    )
    subscription = models.ForeignKey(
        Subscription, blank=True, null=True,
        on_delete=models.SET_NULL,
        related_name='orders',
    )

    first_name = models.CharField(max_length=256, blank=True)
    last_name = models.CharField(max_length=256, blank=True)
    company_name = models.CharField(max_length=256, blank=True)
    street_address_1 = models.CharField(max_length=256, blank=True)
    street_address_2 = models.CharField(max_length=256, blank=True)
    city = models.CharField(max_length=256, blank=True)
    postcode = models.CharField(max_length=20, blank=True)
    country = CountryField(blank=True)

    user_email = models.EmailField(blank=True, default='')

    currency = models.CharField(
        max_length=3, default=settings.DEFAULT_CURRENCY
    )
    total_net = models.DecimalField(
        max_digits=12,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0)
    total_gross = models.DecimalField(
        max_digits=12,
        decimal_places=settings.DEFAULT_DECIMAL_PLACES, default=0)
    total = TaxedMoneyField(
        net_amount_field='total_net',
        gross_amount_field='total_gross',
        currency="currency",
    )

    # FIXME: https://github.com/mirumee/django-prices/issues/71
    total.unique = False

    is_donation = models.BooleanField(default=False)
    description = models.CharField(max_length=255, blank=True)
    customer_note = models.TextField(blank=True, default='')
    kind = models.CharField(max_length=255, default='', blank=True)

    remote_reference = models.CharField(max_length=256, blank=True)
    token = models.UUIDField(default=uuid.uuid4, db_index=True)

    service_start = models.DateTimeField(null=True, blank=True)
    service_end = models.DateTimeField(null=True, blank=True)

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

    @property
    def is_recurring(self):
        return bool(self.subscription_id)

    def get_service_label(self):
        if not self.subscription:
            return self.description
        return order_service_description(
            self, self.subscription.plan.interval
        )

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

    def is_tentatively_paid(self):
        tentatively_paid = sum([
            payment.total for payment in
            self.payments.filter(status__in=(
                PaymentStatus.CONFIRMED,
                PaymentStatus.PENDING,
                PaymentStatus.PREAUTH
            ))],
            ZERO_TAXED_MONEY
        )
        return tentatively_paid.gross >= self.total.gross

    def get_payment_amounts(self):
        tentative_status = (
            PaymentStatus.CONFIRMED,
            PaymentStatus.PENDING,
            PaymentStatus.PREAUTH
        )

        payments = self.payments.filter(status__in=tentative_status)

        amounts = defaultdict(lambda: ZERO_MONEY)
        for payment in payments:
            amounts['tentative'] += payment.get_amount()
            if payment.status in (PaymentStatus.CONFIRMED,):
                amounts['total'] += payment.get_captured_amount()
        return amounts

    def get_absolute_url(self):
        return reverse('froide_payment:order-detail', kwargs={
            'token': str(self.token)
        })

    def get_absolute_payment_url(self, variant):
        return reverse('froide_payment:start-payment', kwargs={
            'token': str(self.token),
            'variant': variant
        })

    def get_failure_url(self):
        obj = self.get_domain_object()
        if obj is not None and hasattr(obj, 'get_failure_url'):
            return obj.get_failure_url()
        return '/'

    def get_success_check_url(self):
        return reverse('froide_payment:order-success', kwargs={
            'token': str(self.token)
        })

    def get_success_url(self):
        obj = self.get_domain_object()
        if obj is not None and hasattr(obj, 'get_success_url'):
            return obj.get_success_url()
        return self.get_absolute_url() + '?result=success'

    def get_domain_object(self):
        model = self.get_domain_model()
        if model is None:
            return None
        try:
            if self.subscription_id and hasattr(model, 'subscription'):
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

    def get_interval_description(self):
        if not self.subscription:
            return ''
        return self.subscription.plan.get_interval_description()

    def get_or_create_payment(self, variant, request=None):
        defaults = get_payment_defaults(self, request=request)
        with transaction.atomic():
            payment, created = Payment.objects.filter(
                models.Q(status=PaymentStatus.WAITING) |
                models.Q(status=PaymentStatus.INPUT) |
                models.Q(status=PaymentStatus.PENDING)
            ).get_or_create(
                variant=variant,
                order=self,
                defaults=defaults
            )
            if created:
                # Delete waiting/input payments from before
                Payment.objects.filter(
                    models.Q(status=PaymentStatus.WAITING) |
                    models.Q(status=PaymentStatus.INPUT),
                ).filter(order=self).exclude(id=payment.id).delete()
        # Trigger signal
        payment.change_status(payment.status)
        return payment


class PaymentStatus(BasePaymentStatus):
    PENDING = 'pending'
    CANCELED = 'canceled'

    CHOICES = [
        (BasePaymentStatus.WAITING,
            pgettext_lazy('payment status', 'Waiting for input')),
        (BasePaymentStatus.PREAUTH,
            pgettext_lazy('payment status', 'Pre-authorized')),
        (BasePaymentStatus.CONFIRMED,
            pgettext_lazy('payment status', 'Confirmed')),
        (BasePaymentStatus.REJECTED,
            pgettext_lazy('payment status', 'Rejected')),
        (BasePaymentStatus.REFUNDED,
            pgettext_lazy('payment status', 'Refunded')),
        (BasePaymentStatus.ERROR,
            pgettext_lazy('payment status', 'Error')),
        (BasePaymentStatus.INPUT,
            pgettext_lazy('payment status', 'Input')),

        (PENDING, pgettext_lazy('payment status', 'Confirmation pending')),
        (CANCELED, pgettext_lazy('payment status', 'Canceled')),
    ]
    CHOICES_DICT = dict(CHOICES)


class Payment(BasePayment):
    status = models.CharField(
        max_length=10, choices=PaymentStatus.CHOICES,
        default=PaymentStatus.WAITING)
    order = models.ForeignKey(
        Order, related_name='payments',
        on_delete=models.PROTECT
    )
    received_amount = models.DecimalField(
        null=True, blank=True,
        max_digits=9, decimal_places=2
    )
    received_timestamp = models.DateTimeField(
        null=True, blank=True
    )

    # FIXME: transaction_id probably needs a db index
    # transaction_id = models.CharField(
    #     max_length=255, blank=True,
    #     db_index=True
    # )

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
        PaymentStatus.CANCELED: 'dark',
    }

    def __str__(self):
        return '{}: {} ({} {} - {})'.format(
            self.order,
            self.get_status_display(),
            self.total,
            self.currency,
            self.variant
        )

    def get_amount(self):
        return Money(
            self.total, self.currency or settings.DEFAULT_CURRENCY
        )

    def get_captured_amount(self):
        return Money(
            self.captured_amount, self.currency or settings.DEFAULT_CURRENCY
        )

    def get_failure_url(self):
        return self.order.get_failure_url()

    def get_success_url(self):
        return self.order.get_success_check_url()

    def get_purchased_items(self):
        order = self.order
        yield PurchasedItem(
            name=str(order.description),
            quantity=1,
            price=order.total_gross,
            currency=order.currency,
            sku=order.id
        )

    def get_variant_display(self):
        return CHECKOUT_PAYMENT_CHOICES_DICT.get(self.variant, '')

    def get_status_display(self):
        return str(PaymentStatus.CHOICES_DICT.get(self.status, self.status))

    @property
    def status_color(self):
        return self.STATUS_COLORS[self.status]

    def is_pending(self):
        return self.status in (
            PaymentStatus.PENDING
        )

    def is_confirmed(self):
        return self.status in (
            PaymentStatus.CONFIRMED
        )

    def is_rejected(self):
        return self.status in (
            PaymentStatus.REJECTED
        )
