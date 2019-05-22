from django import forms
from django.conf import settings


class PriceInput(forms.TextInput):
    template_name = "froide_payment/widgets/price_input.html"

    def get_context(self, name, value, attrs):
        ctx = super(PriceInput, self).get_context(name, value, attrs)
        ctx['widget'].setdefault('attrs', {})
        ctx['widget']['attrs']['class'] = 'form-control col-3'
        ctx['widget']['attrs']['pattern'] = "[\\d\\.,]*"
        ctx['currency'] = settings.DEFAULT_CURRENCY
        return ctx
