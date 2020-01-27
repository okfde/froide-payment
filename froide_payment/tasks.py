from datetime import timedelta

from django.utils import timezone
from django.db.models import Q, Count

from celery import shared_task

from .utils import create_recurring_order


@shared_task(name='froide_payment.cleanup')
def froide_payment_cleanup():
    from .models import Payment, Order, PaymentStatus

    now = timezone.now()

    time_ago = now - timedelta(hours=12)

    # Delete payments that are more than 12 hours old
    # and still in waiting or input status
    Payment.objects.filter(
        created__lte=time_ago,
    ).filter(
        Q(status=PaymentStatus.WAITING) |
        Q(status=PaymentStatus.INPUT)
    ).delete()

    # Get old orders without payments
    non_payment_orders = Order.objects.filter(
        created__lte=time_ago
    ).annotate(
        payment_count=Count('payments')
    ).filter(
        payment_count=0
    )
    non_payment_orders.delete()
    # Remove subscriptions?
    # Remove customers?


@shared_task(name='froide_payment.lastschrift_subscriptions')
def lastschrift_subscriptions():
    from .models import Subscription
    from .provider.lastschrift import LastschriftProvider

    now = timezone.now()
    four_days_ago = now - timedelta(days=4)

    provider_name = LastschriftProvider.provider_name

    active_subscriptions = Subscription.objects.filter(
        active=True,
        plan__provider=provider_name
    ).filter(
        Q(next_date__isnull=True) | Q(next_date__lte=four_days_ago)
    )
    for subscription in active_subscriptions:
        create_recurring_order(
            subscription, now=now
        )
