import csv
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.http import StreamingHttpResponse
from django.utils.translation import ugettext_lazy as _
from django.template.loader import render_to_string
from django.core.mail import send_mail
from django.utils import timezone

try:
    from froide.helper.email_sending import mail_registry
except ImportError:
    mail_registry = None


lastschrift_mail = None
if mail_registry is not None:
    lastschrift_mail = mail_registry.register(
        'froide_payment/email/lastschrift_triggered',
        ('payment', 'order', 'note')
    )


def get_client_ip(request=None):
    if request is None:
        return None
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[-1].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_payment_defaults(order, request=None):
    return {
        'total': order.amount,
        'delivery': Decimal('0.0'),
        'tax': Decimal('0.0'),
        'currency': settings.DEFAULT_CURRENCY,
        'billing_first_name': order.first_name,
        'billing_last_name': order.last_name,
        'billing_address_1': order.street_address_1,
        'billing_address_2': order.street_address_2,
        'billing_city': order.city,
        'billing_postcode': order.postcode,
        'billing_country_code': order.country,
        'billing_email': order.user_email,
        'description': order.description,
        'customer_ip_address': get_client_ip(request)
    }


def dicts_to_csv_response(generator, name='export.csv'):
    response = StreamingHttpResponse(
        dict_to_csv_stream(generator),
        content_type='text/csv'
    )
    response['Content-Disposition'] = 'attachment; filename="%s"' % name
    return response


class FakeFile(object):
    def write(self, string):
        self._last_string = string.encode('utf-8')


def dict_to_csv_stream(stream):
    writer = None
    fake_file = FakeFile()
    for d in stream:
        if writer is None:
            field_names = list(d.keys())
            writer = csv.DictWriter(fake_file, field_names)
            writer.writeheader()
            yield fake_file._last_string
        writer.writerow(d)
        yield fake_file._last_string


def interval_description(interval):
    if interval == 0:
        return _('one time')
    elif interval == 1:
        return _('every month')
    elif interval == 3:
        return _('every three months')
    if interval == 6:
        return _('every six months')
    if interval == 12:
        return _('every year')
    return _('every {} months') % interval


def send_lastschrift_mail(payment, note=''):
    if payment.variant != 'lastschrift':
        return

    order = payment.order

    context = {
        'payment': payment,
        'order': order,
        'note': note
    }
    subject = 'SEPA-Lastschriftmandat: {}'.format(order.description)
    # Send email about Lastschrift
    if lastschrift_mail is not None:
        lastschrift_mail.send(
            email=payment.billing_email, context=context,
            subject=subject,
            priority=True
        )
    else:
        send_mail(
            subject,
            render_to_string(
                'froide_payment/email/lastschrift_triggered.txt',
                context
            ),
            settings.DEFAULT_FROM_EMAIL,
            [payment.billing_email],
            fail_silently=False,
        )


def create_recurring_order(subscription,
                           remote_reference=None, now=None, force=False):
    from .models import PaymentStatus

    if now is None:
        now = timezone.now()

    if not subscription.active:
        return

    provider_name = subscription.plan.provider
    seven_days_ago = now - timedelta(days=7)

    last_order = subscription.get_last_order()

    if not force and last_order.service_end > seven_days_ago:
        # Not yet due, set next_date correctly
        subscription.next_date = last_order.service_end
        subscription.save()
        return

    if remote_reference is None:
        remote_reference = subscription.remote_reference
    order = subscription.create_order(
        remote_reference=remote_reference
    )
    payment = order.get_or_create_payment(provider_name)
    subscription.last_date = order.created
    subscription.next_date = order.service_end
    subscription.save()
    if provider_name == 'lastschrift':
        customer = subscription.customer
        customer_data = customer.data
        payment.attrs.mandats_id = customer_data.get('mandats_id', None)
        payment.attrs.iban = customer_data.get('iban', None)

    payment.change_status(PaymentStatus.PENDING)
    return payment
