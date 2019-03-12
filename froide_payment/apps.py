from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _


class FroidePaymentConfig(AppConfig):
    name = 'froide_payment'
    verbose_name = _("Froide Payment App")
