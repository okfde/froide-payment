import csv
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Count, Q
from django.http import StreamingHttpResponse
from django.template.loader import render_to_string
from django.utils import formats, timezone
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


def get_client_ip(request=None):
    if request is None:
        return None
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[-1].strip()
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


def get_payment_defaults(order, request=None):
    return {
        "total": order.amount,
        "delivery": Decimal("0.0"),
        "tax": Decimal("0.0"),
        "currency": settings.DEFAULT_CURRENCY,
        "billing_first_name": order.first_name,
        "billing_last_name": order.last_name,
        "billing_address_1": order.street_address_1,
        "billing_address_2": order.street_address_2,
        "billing_city": order.city,
        "billing_postcode": order.postcode,
        "billing_country_code": order.country,
        "billing_email": order.user_email,
        "description": order.description,
        "customer_ip_address": get_client_ip(request),
    }


def dicts_to_csv_response(generator, name="export.csv"):
    response = StreamingHttpResponse(
        dict_to_csv_stream(generator), content_type="text/csv"
    )
    response["Content-Disposition"] = 'attachment; filename="%s"' % name
    return response


class FakeFile(object):
    def write(self, string):
        self._last_string = string.encode("utf-8")


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
        return _("one time")
    elif interval == 1:
        return _("every month")
    elif interval == 3:
        return _("every three months")
    if interval == 6:
        return _("every six months")
    if interval == 12:
        return _("every year")
    return _("every {} months") % interval


def order_service_description(order, interval):
    if interval == 1:
        return formats.date_format(order.service_start, "m/Y")
    elif interval > 1:
        return "{}-{}".format(
            formats.date_format(order.service_start, "m/Y"),
            formats.date_format(order.service_end, "m/Y"),
        )
    return ""


def send_lastschrift_mail(payment, note=""):
    if payment.variant != "lastschrift":
        return

    order = payment.order

    context = {"payment": payment, "order": order, "note": note}
    subject = "SEPA-Lastschriftmandat: {}".format(order.description)
    send_mail(
        subject,
        render_to_string("froide_payment/email/lastschrift_triggered.txt", context),
        settings.DEFAULT_FROM_EMAIL,
        [payment.billing_email],
        fail_silently=False,
    )


def send_sepa_mail(payment, data):
    if payment.variant != "sepa":
        return

    order = payment.order

    context = {
        "payment": payment,
        "order": order,
    }
    context.update(data)
    subject = "SEPA-Lastschriftmandat: {}".format(order.description)
    send_mail(
        subject,
        render_to_string("froide_payment/email/sepa_notification.txt", context),
        settings.DEFAULT_FROM_EMAIL,
        [payment.billing_email],
        fail_silently=False,
    )


def create_recurring_order(
    subscription,
    remote_reference=None,
    now=None,
    force=False,
    remote_reference_is_unique=False,
):
    from .models import PaymentStatus

    if now is None:
        now = timezone.now()

    if subscription.canceled:
        return

    provider_name = subscription.plan.provider

    last_order = subscription.get_last_order()

    now += timedelta(days=1)

    if not force and now < last_order.service_end:
        # Not yet due, set next_date correctly
        subscription.next_date = last_order.service_end
        subscription.save()
        return

    logger.info(
        "Create recurring order for subscription %s based on order %s",
        subscription.id,
        last_order.id,
    )

    if remote_reference is None:
        remote_reference = subscription.remote_reference
    order = subscription.create_order(
        remote_reference=remote_reference,
        remote_reference_is_unique=remote_reference_is_unique,
    )
    payment = order.get_or_create_payment(provider_name)
    subscription.last_date = order.created
    subscription.next_date = order.service_end
    subscription.save()
    if provider_name == "lastschrift":
        customer = subscription.customer
        customer_data = customer.data
        payment.attrs.mandats_id = customer_data.get("mandats_id", None)
        payment.attrs.iban = customer_data.get("iban", None)

    payment.change_status(PaymentStatus.PENDING)
    payment.save()
    logger.info("Payment %s created for subscription %s", payment.id, subscription.id)

    return payment


def cleanup(time_ago=None):
    from .models import Customer, Order, Payment, PaymentStatus, Subscription

    if time_ago is None:
        now = timezone.now()
        time_ago = now - timedelta(hours=12)

    # Delete payments that are more than 12 hours old
    # and still in waiting or input status
    inactive_payments = Payment.objects.filter(
        created__lte=time_ago,
    ).filter(Q(status=PaymentStatus.WAITING) | Q(status=PaymentStatus.INPUT))
    logger.warn("Deleting %s inactive payments", inactive_payments.count())
    inactive_payments.delete()

    # Get old orders without payments
    non_payment_orders = (
        Order.objects.filter(created__lte=time_ago)
        .annotate(payment_count=Count("payments"))
        .filter(payment_count=0)
    )
    logger.warn("Deleting %s inactive orders", non_payment_orders.count())
    non_payment_orders.delete()

    # Delete older subscriptions without connected orders
    non_order_subscriptions = (
        Subscription.objects.filter(
            created__lte=time_ago,
        )
        .annotate(order_count=Count("orders"))
        .filter(order_count=0)
    )
    logger.warn("Deleting %s inactive subscriptions", non_order_subscriptions.count())
    non_order_subscriptions.delete()

    # Delete customers without order or subscriptions
    dangling_customers = (
        Customer.objects.filter(created__lte=time_ago)
        .annotate(
            order_count=Count("orders"),
            subscription_count=Count("subscriptions"),
        )
        .filter(order_count=0, subscription_count=0)
    )
    logger.warn("Deleting %s obsolete customers", dangling_customers.count())
    dangling_customers.delete()
