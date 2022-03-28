from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class FroidePaymentConfig(AppConfig):
    name = "froide_payment"
    verbose_name = _("Froide Payment App")

    def ready(self):
        from payments.signals import status_changed

        from .listeners import subscription_payment

        status_changed.connect(subscription_payment)
