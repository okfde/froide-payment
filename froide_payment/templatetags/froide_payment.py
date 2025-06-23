from django import template
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _

from ..utils import get_quickpayment_provider

register = template.Library()


@register.simple_tag
def render_payment_status(payment):
    template_base = "froide_payment/payment/status/{}.html"
    return render_to_string(
        [
            template_base.format(payment.variant),
            template_base.format("default"),
        ],
        {"payment": payment, "order": payment.order},
    )


@register.inclusion_tag("froide_payment/payment/_quickpayment.html", takes_context=True)
def render_quickpayment(context):
    amount_cents = context.get("amount", 0) * 100
    provider = get_quickpayment_provider()
    element_id = context.get("id", "quick-payment")
    return {
        "quickpayment_id": element_id,
        "quickpayment_data_id": element_id + "-data",
        "loading": context.get("loading", False),
        "quickpayment_data": {
            "action": context.get("action", ""),
            "stripepk": provider.public_key,
            "stripecountry": getattr(settings, "STRIPE_COUNTRY", "DE"),
            "currency": settings.DEFAULT_CURRENCY.lower(),
            "amount": amount_cents,
            "interval": context.get("interval", 0),
            "label": str(_("Donation to {}").format(settings.SITE_NAME)),
            "sitename": settings.SITE_NAME,
            "locale": context["request"].LANGUAGE_CODE,
            "donation": context.get("is_donation", True),
            "successurl": settings.SITE_URL,
        },
    }
