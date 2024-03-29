from django import template
from django.template.loader import render_to_string

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
