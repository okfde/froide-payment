import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404
from django.contrib import messages
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _

from froide.helper.utils import get_client_ip

from payments import RedirectNeeded, PaymentStatus

from .models import Payment, Order, CHECKOUT_PAYMENT_CHOICES


logger = logging.getLogger(__name__)


def start_payment(request, token, variant):
    order = get_object_or_404(Order, token=token)
    if order.is_fully_paid():
        return redirect(order.get_success_url())

    defaults = {
        'total': order.amount,
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
        except Exception:
            logger.exception('Error communicating with the payment gateway')
            msg = _('Oops, it looks like we were unable to contact the '
                    'selected payment service')
            messages.error(request, msg)
            payment.change_status(PaymentStatus.ERROR)
            return redirect('froide_payment:payment', token=order.token)
    default_template = 'froide_payment/payment/default.html'
    template = 'froide_payment/payment/%s.html' % variant
    ctx = {
        'form': form,
        'payment': payment,
        'order': order,
    }
    return render(request, [template, default_template], ctx)
