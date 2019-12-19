from .models import PaymentStatus


def subscription_payment(sender=None, instance=None, **kwargs):
    order = instance.order
    if not order.is_recurring:
        return

    subscription = order.subscription
    active = subscription.active

    if instance.status == PaymentStatus.CONFIRMED:
        if order.is_fully_paid():
            active = True
    elif instance.status in (
            PaymentStatus.ERROR, PaymentStatus.REFUNDED,
            PaymentStatus.REJECTED):
        active = False

    if active != subscription.active:
        subscription.active = active
        subscription.save()
