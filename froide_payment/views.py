from decimal import Decimal
import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404
from django.conf import settings
from django.db import transaction
from django.db.models import Q

from froide.helper.utils import get_client_ip, render_403

from payments import RedirectNeeded
from payments.core import provider_factory

from .models import (
    Payment, Order, PaymentStatus, CHECKOUT_PAYMENT_CHOICES
)


logger = logging.getLogger(__name__)


def order_detail(request, token):
    order = get_object_or_404(Order, token=token)
    user = request.user
    if order.user and user != order.user and not user.is_superuser:
        return render_403(request)

    payments = Payment.objects.filter(order=order)
    templates = []
    if order.kind:
        part = '/'.join(order.kind.lower().split('.'))
        templates.append('froide_payment/order/%s/detail.html' % part)
    templates.append('froide_payment/order/default.html')

    domain_object = order.get_domain_object()

    result = request.GET.get('result')
    if result == 'success':
        any_confirmed = any(
            payment.status == PaymentStatus.CONFIRMED
            for payment in payments
        )
        if not any_confirmed:
            for payment in payments:
                provider = provider_factory(payment.variant)
                if hasattr(provider, 'update_status'):
                    provider.update_status(payment)

    ctx = {
        'payments': payments,
        'order': order,
        'object': domain_object,
        'result': result
    }
    return render(request, templates, ctx)


def start_payment(request, token, variant):
    order = get_object_or_404(Order, token=token)
    if order.is_fully_paid():
        return redirect(order.get_success_url())

    defaults = {
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
    if variant not in [code for code, dummy_name in CHECKOUT_PAYMENT_CHOICES]:
        raise Http404('%r is not a valid payment variant' % (variant,))
    with transaction.atomic():
        payment, created = Payment.objects.filter(
            Q(status=PaymentStatus.WAITING) |
            Q(status=PaymentStatus.INPUT)
        ).get_or_create(
            variant=variant,
            order=order,
            defaults=defaults
        )
        try:
            form = payment.get_form(data=None)
        except RedirectNeeded as redirect_to:
            return redirect(str(redirect_to))
    default_template = 'froide_payment/payment/default.html'
    template = 'froide_payment/payment/%s.html' % variant
    ctx = {
        'form': form,
        'payment': payment,
        'order': order,
    }
    return render(request, [template, default_template], ctx)
