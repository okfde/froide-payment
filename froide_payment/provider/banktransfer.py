from django.utils.crypto import get_random_string

from payments.core import BasicProvider
from payments import RedirectNeeded

from ..models import PaymentStatus
from ..forms import LastschriftPaymentForm

from .mixins import PlanProductMixin


CODE_CHARS = 'ACDEFHJKLMNPRSTUWXY3469'


def generate_transfer_code():
    return 'FDS ' + get_random_string(length=8, allowed_chars=CODE_CHARS)


class BanktransferProvider(PlanProductMixin, BasicProvider):
    provider_name = 'banktransfer'
    form_class = LastschriftPaymentForm

    def get_form(self, payment, data=None):
        '''
        Bank transfer gets stored and processed
        '''
        if payment.status == PaymentStatus.WAITING:
            payment.change_status(PaymentStatus.INPUT)

        order = payment.order

        transaction_id = ''
        if order.is_recurring:
            subscription = order.subscription
            if not subscription.remote_reference:
                transaction_id = generate_transfer_code()
                subscription.remote_reference = transaction_id
                subscription.save()
            else:
                transaction_id = subscription.remote_reference

        if not payment.transaction_id:
            if not transaction_id:
                transaction_id = generate_transfer_code()
            payment.transaction_id = transaction_id
            payment.save()

        if not order.remote_reference:
            if not transaction_id:
                transaction_id = generate_transfer_code()
            order.remote_reference = transaction_id
            order.save()

        if order.is_recurring:
            raise RedirectNeeded(order.subscription.get_absolute_url())
        raise RedirectNeeded(payment.order.get_absolute_url())
