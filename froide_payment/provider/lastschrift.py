from payments.core import BasicProvider
from payments import RedirectNeeded

from ..models import PaymentStatus
from ..forms import LastschriftPaymentForm

from .mixins import PlanProductMixin


class IBANProviderMixin:
    def get_form(self, payment, data=None):
        '''
        Lastschrift gets stored and processed
        '''
        if payment.status == PaymentStatus.WAITING:
            payment.change_status(PaymentStatus.INPUT)

        iban = None
        try:
            iban = payment.attrs.iban
        except KeyError:
            pass
        if iban is None and payment.order.customer:
            customer = payment.order.customer
            iban = customer.data.get('iban', None)

        if iban is not None:
            if payment.status == PaymentStatus.INPUT:
                payment.change_status(PaymentStatus.PENDING)
            raise RedirectNeeded(payment.get_success_url())

        form = self.form_class(
            data=data, payment=payment, provider=self,
            hidden_inputs=False
        )
        if data is not None:
            if form.is_valid():
                form.save()
                raise RedirectNeeded(payment.get_success_url())

        return form


class LastschriftProvider(PlanProductMixin, IBANProviderMixin, BasicProvider):
    provider_name = 'lastschrift'
    form_class = LastschriftPaymentForm
