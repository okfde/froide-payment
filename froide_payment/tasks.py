from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from celery import shared_task

from .utils import cleanup, create_recurring_order


@shared_task(name="froide_payment.cleanup")
def froide_payment_cleanup():
    cleanup()


@shared_task(name="froide_payment.lastschrift_subscriptions")
def lastschrift_subscriptions():
    from .models import Subscription
    from .provider.lastschrift import LastschriftProvider

    now = timezone.now()
    four_days_ago = now - timedelta(days=4)

    provider_name = LastschriftProvider.provider_name

    active_subscriptions = Subscription.objects.filter(
        active=True, plan__provider=provider_name
    ).filter(Q(next_date__isnull=True) | Q(next_date__lte=four_days_ago))
    for subscription in active_subscriptions:
        create_recurring_order(subscription, now=now)
