__version__ = '0.0.1'

from django.conf import settings
from django.utils.translation import ugettext_lazy as _

CHECKOUT_PAYMENT_CHOICES = [
    ('creditcard', _('Credit Card')),
    ('sepa', _('SEPA Debit')),
]

PAYMENT_METHODS = [
    variant for variant in CHECKOUT_PAYMENT_CHOICES
    if variant[0] in settings.PAYMENT_VARIANTS
]
