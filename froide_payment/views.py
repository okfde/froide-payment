import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404

from payments import RedirectNeeded
from payments.core import provider_factory

from .models import (
    Payment, Order, Subscription, PaymentStatus, CHECKOUT_PAYMENT_CHOICES
)


logger = logging.getLogger(__name__)


def order_detail(request, token):
    order = get_object_or_404(Order, token=token)
    user = request.user
    if order.user and user != order.user and not user.is_superuser:
        return redirect('/')

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

    if variant not in [code for code, dummy_name in CHECKOUT_PAYMENT_CHOICES]:
        raise Http404('%r is not a valid payment variant' % (variant,))

    payment = order.get_or_create_payment(variant, request=request)

    data = None
    if request.method == 'POST':
        data = request.POST
    try:
        form = payment.get_form(data=data)
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


def subscription_detail(request, token):
    subscription = get_object_or_404(Subscription, token=token)
    user = request.user
    customer = subscription.customer
    if customer.user and user != customer.user and not user.is_superuser:
        return redirect('/')

    templates = []
    plan = subscription.plan
    if plan.provider:
        part = plan.provider.lower()
        templates.append(
            'froide_payment/subscription/%s/detail.html' % part
        )
    templates.append('froide_payment/subscription/default.html')

    orders = Order.objects.filter(subscription=subscription)

    ctx = {
        'orders': orders,
        'subscription': subscription,
    }
    return render(request, templates, ctx)
