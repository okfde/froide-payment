from decimal import Decimal

from django.utils.text import slugify

from payments.core import BasicProvider
from payments import RedirectNeeded

from ..models import PaymentStatus, Product, Plan
from ..forms import LastschriftPaymentForm


class LastschriftProvider(BasicProvider):
    provider_name = 'lastschrift'
    form_class = LastschriftPaymentForm

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

    def get_or_create_product(self, category):
        try:
            product = Product.objects.get(
                category=category,
                provider=self.provider_name
            )
        except Product.DoesNotExist:
            product = Product.objects.create(
                name='{provider} {category}'.format(
                    provider=self.provider_name,
                    category=category
                ),
                category=category,
                provider=self.provider_name,
            )
        return product

    def get_or_create_plan(self, plan_name, category, amount, month_interval):
        product = self.get_or_create_product(category)
        try:
            plan = Plan.objects.get(
                product=product,
                amount=amount,
                interval=month_interval,
                provider=self.provider_name
            )
        except Plan.DoesNotExist:
            plan = Plan.objects.create(
                name=plan_name,
                slug=slugify(plan_name),
                category=category,
                amount=amount,
                interval=month_interval,
                amount_year=amount * Decimal(12 / month_interval),
                provider=self.provider_name,
                product=product
            )
        return plan
