import json
import logging
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_permission_codename
from django.core.exceptions import BadRequest
from django.core.mail import mail_admins
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from froide.helper.utils import render_403
from payments import RedirectNeeded
from payments.core import provider_factory

from .forms import ModifySubscriptionForm
from .models import Order, Payment, PaymentStatus, Subscription
from .signals import subscription_cancel_feedback

logger = logging.getLogger(__name__)


def can_access(obj, user):
    if user.is_superuser:
        return True

    opts = obj._meta
    codename = get_permission_codename("change", opts)
    perm = "%s.%s" % (opts.app_label, codename)
    if user.is_staff and user.has_perm(perm):
        return True
    if obj.user and user != obj.user:
        return False
    return True


def check_subscription_access(func):
    @wraps(func)
    def inner(request, token, *args, **kwargs):
        subscription = get_object_or_404(Subscription, token=token)
        user = request.user
        customer = subscription.customer
        if can_access(customer, user):
            return func(request, subscription, *args, **kwargs)
        return render_403(request)

    return inner


def order_detail(request, token):
    order = get_object_or_404(Order, token=token)
    user = request.user

    if "json" in request.META.get("HTTP_ACCEPT", ""):
        return JsonResponse({"name": order.get_full_name()})

    if not can_access(order, user):
        return redirect("/")

    payments = Payment.objects.filter(order=order)
    templates = []
    if order.kind:
        part = "/".join(order.kind.lower().split("."))
        templates.append("froide_payment/order/%s/detail.html" % part)
    templates.append("froide_payment/order/default.html")

    domain_object = order.get_domain_object()

    result = request.GET.get("result")
    if result == "success":
        any_confirmed = any(
            payment.status == PaymentStatus.CONFIRMED for payment in payments
        )
        if not any_confirmed:
            for payment in payments:
                provider = provider_factory(payment.variant)
                if hasattr(provider, "update_status"):
                    provider.update_status(payment)

    ctx = {
        "payments": payments,
        "order": order,
        "object": domain_object,
        "result": result,
    }
    return render(request, templates, ctx)


def order_success(request, token):
    order = get_object_or_404(Order, token=token)
    user = request.user
    if not can_access(order, user):
        return redirect("/")

    payments = Payment.objects.filter(order=order)

    any_confirmed = any(
        payment.status == PaymentStatus.CONFIRMED for payment in payments
    )
    if not any_confirmed:
        for payment in payments:
            provider = provider_factory(payment.variant)
            if hasattr(provider, "update_status"):
                provider.update_status(payment)

    return redirect(order.get_success_url())


def order_failed(request, token):
    order = get_object_or_404(Order, token=token)
    user = request.user
    if not can_access(order, user):
        return redirect("/")

    return redirect(order.get_failure_url())


def start_payment(request, token, variant):
    order = get_object_or_404(Order, token=token)
    if order.is_fully_paid():
        return redirect(order.get_success_url())

    if variant not in settings.PAYMENT_VARIANTS:
        return redirect(order)

    payment = order.get_or_create_payment(variant, request=request)

    data = None
    if request.method == "POST":
        data = request.POST
    try:
        form = payment.get_form(data=data)
    except RedirectNeeded as redirect_to:
        return redirect(str(redirect_to))

    default_template = "froide_payment/payment/default.html"
    template = "froide_payment/payment/%s.html" % variant
    ctx = {
        "form": form,
        "payment": payment,
        "order": order,
    }
    return render(request, [template, default_template], ctx)


@check_subscription_access
def subscription_detail(request, subscription):
    templates = []
    plan = subscription.plan
    if plan.provider:
        part = plan.provider.lower()
        templates.append("froide_payment/subscription/%s/detail.html" % part)
    templates.append("froide_payment/subscription/default.html")

    orders = Order.objects.filter(subscription=subscription).order_by("-created")

    payment_method_form = None
    provider = provider_factory(subscription.plan.provider)
    if (
        subscription.active
        and not subscription.canceled
        and hasattr(provider, "get_change_payment_method_form")
    ):
        payment_method_form = provider.get_change_payment_method_form(subscription)

    ctx = {
        "orders": orders,
        "subscription": subscription,
        "cancel_info": subscription.get_cancel_info(),
        "modify_info": subscription.get_modify_info(),
        "modify_form": ModifySubscriptionForm(subscription=subscription),
        "payment_method_form": payment_method_form,
    }
    return render(request, templates, ctx)


@require_POST
@check_subscription_access
def subscription_cancel(request, subscription):
    cancel_info = subscription.get_cancel_info()
    if not subscription.active or subscription.canceled or not cancel_info.can_cancel:
        return redirect(subscription)

    user = None
    if request.user.is_authenticated:
        user = request.user

    trigger = "admin" if request.user.is_staff else "website"
    success = subscription.cancel(user=user, trigger=trigger)

    subscription_cancel_feedback.send(
        sender=subscription,
        data=request.POST,
    )

    if success:
        messages.add_message(
            request, messages.INFO, _("Your subscription has been canceled.")
        )
    else:
        mail_admins(
            "Subscription cancelation failed", "Subscription ID: %s" % subscription.id
        )
        messages.add_message(
            request,
            messages.ERROR,
            _(
                "An error occurred with our payment provider. "
                "We will investigate and make sure your subscription is "
                "properly canceled."
            ),
        )

    return redirect(subscription)


@require_POST
@check_subscription_access
def subscription_modify(request, subscription):
    customer = subscription.customer
    form = ModifySubscriptionForm(request.POST, subscription=subscription)
    if not subscription.get_modify_info().can_modify:
        raise BadRequest("Subscription can't be modified")

    if form.is_valid():
        if customer.user or request.user.has_perm("froide_payment.change_subscription"):
            # Subscription customer has a user and previous check has established access
            success = form.save()
            if success:
                messages.add_message(
                    request, messages.INFO, _("Your subscription has been modified.")
                )
            else:
                messages.add_message(
                    request,
                    messages.ERROR,
                    _(
                        "There was an error modifying your subscription with our payment provider."
                    ),
                )
                mail_admins(
                    "Subscription modification failed",
                    "Subscription ID: %s" % subscription.id,
                )
        else:
            # Subscription customer has no user, so we need to confirm the modification
            form.send_confirmation_email()
            messages.add_message(
                request,
                messages.INFO,
                _("We have sent a confirmation email to your email address."),
            )

    else:
        messages.add_message(
            request, messages.ERROR, _("There was an error with your input.")
        )

    return redirect(subscription)


@check_subscription_access
def subscription_modify_confirm(request, subscription):
    form = ModifySubscriptionForm(subscription=subscription)
    try:
        data = form.get_form_data_from_code(request.GET.get("code", ""))
    except ValueError as e:
        messages.add_message(request, messages.ERROR, str(e))
        return redirect(subscription)
    form = ModifySubscriptionForm(data=data, subscription=subscription)
    if form.is_valid():
        # Subscription customer email has confirmed the modification
        success = form.save()
        if success:
            messages.add_message(
                request, messages.INFO, _("Your subscription has been modified.")
            )
        else:
            messages.add_message(
                request,
                messages.ERROR,
                _(
                    "There was an error modifying your subscription with our payment provider."
                ),
            )
            mail_admins(
                "Subscription modification failed",
                "Subscription ID: %s" % subscription.id,
            )

    else:
        messages.add_message(
            request, messages.ERROR, _("There was an error with your input.")
        )
    return redirect(subscription)


@require_POST
@check_subscription_access
def subscription_payment_method(request, subscription):
    provider = provider_factory(subscription.plan.provider)
    if not hasattr(provider, "get_change_payment_method_form"):
        messages.add_message(
            request,
            messages.ERROR,
            _(
                "Your subscription provider does not support changing the payment method."
            ),
        )
        return redirect(subscription)
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return redirect(subscription)
    data = json.loads(request.body.decode("utf-8"))
    form = provider.get_change_payment_method_form(subscription, data=data)
    if form.is_valid():
        message = provider.update_payment_method(subscription, form.payment_method)
        if message:
            messages.add_message(request, messages.SUCCESS, message)
            return JsonResponse({"status": "success"})
    return JsonResponse({"error": _("An error occurred.")})
