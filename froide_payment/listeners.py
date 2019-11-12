import json

from django.conf import settings
from django.template.loader import render_to_string
from django.core.mail import send_mail

try:
    from froide.helper.email_sending import mail_registry
except ImportError:
    mail_registry = None

from .models import PaymentStatus


lastschrift_mail = None
if mail_registry is not None:
    lastschrift_mail = mail_registry.register(
        'froide_payment/email/lastschrift_captured',
        ('payment', 'order',)
    )


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


def lastschrift_payment(sender=None, instance=None, **kwargs):
    if instance.variant != 'lastschrift':
        return
    if instance.status != PaymentStatus.CONFIRMED:
        return

    order = instance.order
    if order.is_recurring:
        # Store mandats_id with customer for future reference
        subscription = order.subscription
        customer = subscription.customer
        customer_data = customer.data
        customer_data['mandats_id'] = instance.attrs.mandats_id
        customer.custom_data = json.dumps(customer_data)
        customer.save()

    context = {
        'payment': instance,
        'order': order
    }
    subject = 'SEPA-Lastschriftmandat: {}'.format(order.description)
    # Send email about Lastschrift
    if lastschrift_mail is not None:
        lastschrift_mail.send(
            email=instance.billing_email, context=context,
            subject=subject,
            priority=True
        )
    else:
        send_mail(
            subject,
            render_to_string(
                'froide_payment/email/lastschrift_captured.txt',
                context
            ),
            settings.DEFAULT_FROM_EMAIL,
            [instance.billing_email],
            fail_silently=False,
        )
