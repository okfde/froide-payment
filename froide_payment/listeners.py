import logging

from .models import PaymentStatus

logger = logging.getLogger(__name__)


def subscription_payment(sender=None, instance=None, **kwargs):
    order = instance.order
    if not order.is_recurring:
        return

    logger.info("Running subscription payment listener for Order %s", order.id)
    subscription = order.subscription
    active = subscription.active

    if instance.status == PaymentStatus.CONFIRMED:
        if order.is_fully_paid():
            active = True
    elif instance.status in (
        PaymentStatus.ERROR,
        PaymentStatus.REFUNDED,
        PaymentStatus.REJECTED,
    ):
        active = False

    if active != subscription.active:
        logger.info(
            "Subscription payment listener for Order %s, " "setting subscription to %s",
            order.id,
            active,
        )

        subscription.active = active
        subscription.save()
