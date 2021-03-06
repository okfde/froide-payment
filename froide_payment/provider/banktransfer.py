import re

from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _

from payments.core import BasicProvider
from payments import RedirectNeeded

from ..models import PaymentStatus
from ..forms import LastschriftPaymentForm

from .mixins import PlanProductMixin
from .utils import CancelInfo


CODE_CHARS = 'ACDEFHJKLMNPRSTUWXY3469'
TRANSFER_PREFIX = 'FDS '  # note trailing space
CODE_LEN = 8

TRANSFER_RE = re.compile('%s?[%s]{%d}' % (
    TRANSFER_PREFIX,
    CODE_CHARS,
    CODE_LEN
), re.I)


def generate_transfer_code():
    return '%s%s' % (
        TRANSFER_PREFIX,
        get_random_string(
            length=CODE_LEN,
            allowed_chars=CODE_CHARS
        )
    )


class BanktransferProvider(PlanProductMixin, BasicProvider):
    provider_name = 'banktransfer'
    form_class = LastschriftPaymentForm

    def get_cancel_info(self, subscription):
        return CancelInfo(
            False,
            _('You need to cancel your standing order with your bank.')
        )

    def cancel_subscription(self, subscription):
        pass

    def get_form(self, payment, data=None):
        '''
        Bank transfer gets stored and need to be done by the user
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

        if payment.status == PaymentStatus.INPUT:
            payment.change_status(PaymentStatus.PENDING)

        raise RedirectNeeded(payment.get_success_url())
