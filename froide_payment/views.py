import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils.translation import gettext_lazy as _
from django.core.mail import mail_admins
from django.http import Http404, JsonResponse
from django.contrib import messages
from django.contrib.auth import get_permission_codename
from django.conf import settings

from payments import RedirectNeeded
from payments.core import provider_factory

from .models import (
    Payment, Order, Subscription, PaymentStatus, CHECKOUT_PAYMENT_CHOICES
)


logger = logging.getLogger(__name__)


def can_access(obj, user):
    if user.is_superuser:
        return True

    opts = obj._meta
    codename = get_permission_codename('change', opts)
    perm = "%s.%s" % (opts.app_label, codename)
    if user.is_staff and user.has_perm(perm):
        return True
    if obj.user and user != obj.user:
        return False
    return True


def order_detail(request, token):
    order = get_object_or_404(Order, token=token)
    user = request.user

    if 'json' in request.META.get('HTTP_ACCEPT', ''):
        return JsonResponse({
            'name': order.get_full_name()
        })

    if not can_access(order, user):
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


def order_success(request, token):
    order = get_object_or_404(Order, token=token)
    user = request.user
    if not can_access(order, user):
        return redirect('/')

    payments = Payment.objects.filter(order=order)

    any_confirmed = any(
        payment.status == PaymentStatus.CONFIRMED
        for payment in payments
    )
    if not any_confirmed:
        for payment in payments:
            provider = provider_factory(payment.variant)
            if hasattr(provider, 'update_status'):
                provider.update_status(payment)

    return redirect(order.get_success_url())


def start_payment(request, token, variant):
    order = get_object_or_404(Order, token=token)
    if order.is_fully_paid():
        return redirect(order.get_success_url())

    if variant not in settings.PAYMENT_VARIANTS:
        return redirect(order)

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
    if not can_access(customer, user):
        return redirect('/')

    templates = []
    plan = subscription.plan
    if plan.provider:
        part = plan.provider.lower()
        templates.append(
            'froide_payment/subscription/%s/detail.html' % part
        )
    templates.append('froide_payment/subscription/default.html')

    orders = Order.objects.filter(
        subscription=subscription
    ).order_by('-created')

    ctx = {
        'orders': orders,
        'subscription': subscription,
        'cancel_info': subscription.get_cancel_info()
    }
    return render(request, templates, ctx)


@require_POST
def subscription_cancel(request, token):
    subscription = get_object_or_404(Subscription, token=token)
    user = request.user
    customer = subscription.customer
    if not can_access(customer, user):
        return redirect('/')

    cancel_info = subscription.get_cancel_info()
    if not subscription.active or not cancel_info.can_cancel:
        return redirect(subscription)

    success = subscription.cancel()

    if success:
        messages.add_message(
            request, messages.INFO,
            _("Your subscription has been canceled.")
        )
    else:
        mail_admins(
            'Subscription cancelation failed',
            'Subscription ID: %s' % subscription.id
        )
        messages.add_message(
            request, messages.ERROR,
            _(
                "An error occurred with our payment provider. "
                "We will investigate and make sure your subscription is "
                "properly canceled."
            )
        )

    return redirect(subscription)
