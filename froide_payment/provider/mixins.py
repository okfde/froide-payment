from decimal import Decimal

from django.utils.text import slugify

from .utils import CancelInfo, ModifyInfo

from ..models import Plan, Product, Subscription


class PlanProductMixin:
    def get_or_create_product(self, category):
        try:
            product = Product.objects.get(
                category=category, provider=self.provider_name
            )
        except Product.DoesNotExist:
            product = Product.objects.create(
                name="{provider} {category}".format(
                    provider=self.provider_name, category=category
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
                provider=self.provider_name,
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
                product=product,
            )
        return plan


class CancelMixin:
    def get_cancel_info(self, subscription: Subscription) -> CancelInfo:
        raise NotImplementedError


class ModifyMixin:
    def get_modify_info(self, subscription: Subscription) -> ModifyInfo:
        raise NotImplementedError


class EditableMixin(CancelMixin, ModifyMixin):
    pass
