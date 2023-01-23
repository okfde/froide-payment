import csv
import json
from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.core.exceptions import PermissionDenied
from django.db.models import Case, F, NullBooleanField, Sum, Value, When
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

import dateutil.parser

from .admin_utils import make_nullfilter
from .models import Customer, Order, Payment, PaymentStatus, Plan, Product, Subscription
from .utils import dicts_to_csv_response, send_lastschrift_mail


class PlanAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    list_display = (
        "name",
        "category",
        "display_amount",
        "provider",
        "interval",
        "created",
    )
    list_filter = ("category", "provider")

    def display_amount(self, obj):
        return "{} {}".format(obj.amount, settings.DEFAULT_CURRENCY)


class CustomerAdmin(admin.ModelAdmin):
    raw_id_fields = ("user",)
    list_display = (
        "user_email",
        "first_name",
        "last_name",
        "created",
    )
    search_fields = (
        "user_email",
        "last_name",
        "first_name",
    )


class SubscriptionAdmin(admin.ModelAdmin):
    readonly_fields = ("canceled", "active")
    raw_id_fields = ("customer",)
    list_display = ("customer", "plan", "created", "next_date", "active", "canceled")
    date_hierarchy = "created"
    list_filter = (
        "active",
        "plan__provider",
        "plan__interval",
        "plan__amount",
        "plan__amount_year",
        "canceled",
    )
    search_fields = (
        "customer__user_email",
        "customer__last_name",
        "customer__first_name",
        "remote_reference",
    )
    actions = ["create_recurring_order", "cancel_subscription"]

    def create_recurring_order(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied

        count = 0
        for sub in queryset:
            res = sub.create_recurring_order()
            if res:
                count += 1

        self.message_user(request, _("%d recurring orders created." % count))

    create_recurring_order.short_description = _("Create next recurring order")

    def cancel_subscription(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied

        count = 0
        success_count = 0
        for sub in queryset:
            count += 1
            if sub.cancel():
                success_count += 1

        self.message_user(
            request,
            _("{success}/{total} subscriptions canceled.").format(
                success=success_count, total=count
            ),
        )

    cancel_subscription.short_description = _("Cancel subscription")


class OrderPaidFilter(admin.SimpleListFilter):
    title = _("Is paid?")
    parameter_name = "is_paid"

    def lookups(self, request, model_admin):
        return (
            ("1", _("Yes")),
            ("0", _("No")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "1":
            return queryset.filter(is_paid=True)
        elif value == "0":
            return queryset.filter(is_paid=False)
        return queryset


class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "user_email",
        "first_name",
        "last_name",
        "created",
        "user",
        "total_net",
        "subscription_plan",
        "service_start",
        "service_end",
        "is_paid",
        "captured_amount",
    )
    date_hierarchy = "created"
    raw_id_fields = (
        "user",
        "customer",
        "subscription",
    )
    list_filter = ("subscription__plan__provider", OrderPaidFilter)
    search_fields = ("user_email", "last_name", "first_name", "remote_reference")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.annotate(
            captured_amount=Sum("payments__captured_amount"),
        )
        qs = qs.annotate(
            is_paid=Case(
                When(captured_amount__gte=F("total_gross"), then=Value(True)),
                default=Value(False),
                output_field=NullBooleanField(),
            )
        )
        return qs.select_related("subscription", "user")

    def is_paid(self, obj):
        return obj.is_paid

    is_paid.admin_order_field = "is_paid"
    is_paid.boolean = True

    def captured_amount(self, obj):
        return obj.captured_amount

    captured_amount.admin_order_field = "captured_amount"

    def subscription_plan(self, obj):
        if obj.subscription:
            return str(obj.subscription.plan)
        return "-"

    subscription_plan.short_description = _("subscription")


class PaymentAdmin(admin.ModelAdmin):
    raw_id_fields = ("order",)
    date_hierarchy = "created"
    list_display = (
        "billing_email",
        "status",
        "variant",
        "created",
        "modified",
        "total",
        "captured_amount",
        "service_label",
    )
    list_filter = (
        "variant",
        "status",
        make_nullfilter("order__subscription", _("subscription order")),
    )
    search_fields = ("transaction_id", "billing_email", "billing_last_name")

    actions = [
        "update_status",
        "export_lastschrift",
        "send_lastschrift_mail",
        "confirm_payments",
        "cancel_payments",
    ]

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            path(
                "import-lastschrift/",
                self.admin_site.admin_view(self.import_lastschrift_result),
                name="froide_payment-payment-import_lastschrift_result",
            ),
            path(
                "convert-lastschrift-to-sepa/<int:payment_id>/",
                self.admin_site.admin_view(self.convert_lastschrift_to_sepa),
                name="froide_payment-payment_convert_lastschrift_to_sepa",
            ),
        ]
        return my_urls + urls

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related(
            "order", "order__subscription", "order__subscription__plan"
        )

    def service_label(self, obj):
        return obj.order.get_service_label()

    def update_status(self, request, queryset):
        for payment in queryset:
            provider = payment.get_provider()
            if hasattr(provider, "update_status"):
                provider.update_status(payment)

    def confirm_payments(self, request, queryset):
        queryset = queryset.filter(status=PaymentStatus.DEFERRED)
        for obj in queryset:
            provider = obj.get_provider()
            provider.confirm_payment(obj)

    def cancel_payments(self, request, queryset):
        queryset = queryset.filter(status=PaymentStatus.DEFERRED)
        for obj in queryset:
            provider = obj.get_provider()
            provider.cancel_payment(obj)

    def export_lastschrift(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied

        def get_lastschrift_export(payment):
            data = {
                "id": str(payment.id),
                "transaction_label": "Spende {}: {} (P{})".format(
                    settings.SITE_NAME, payment.order.get_service_label(), payment.id
                ),
                "amount": str(payment.total),
                "currency": payment.currency,
                "name": " ".join(
                    [
                        payment.billing_first_name,
                        payment.billing_last_name,
                    ]
                ),
                "iban": payment.attrs.iban,
                "failed": "",
                "captured": "",
            }

            return data

        # Only export pending lastschrift
        base_queryset = queryset.filter(
            variant="lastschrift",
            status=PaymentStatus.PENDING,
        )
        # Mark rows to be processed with timestamp
        queryset = base_queryset.exclude(extra_data__contains='"processing":')
        now = str(timezone.now().isoformat())
        for lastschrift in queryset:
            lastschrift.attrs.processing = now
            lastschrift.save()

        # Export to be processed rows
        queryset = base_queryset.filter(
            extra_data__contains='"processing": "{}"'.format(now)
        )
        queryset = queryset.select_related("order")

        filename = "lastschrift_{}.csv".format(
            timezone.now().isoformat(timespec="minutes")
        )
        dict_generator = (get_lastschrift_export(payment) for payment in queryset)
        return dicts_to_csv_response(dict_generator, name=filename)

    def import_lastschrift_result(self, request):
        if not request.method == "POST":
            raise PermissionDenied
        if not self.has_change_permission(request):
            raise PermissionDenied

        csv_file = request.FILES.get("file")
        csv_file = StringIO(csv_file.read().decode("utf-8"))
        reader = csv.DictReader(csv_file)
        rows = [row for row in reader]
        row_map = {int(row["id"]): row for row in rows}
        row_ids = list(row_map.keys())
        payments = Payment.objects.filter(variant="lastschrift", id__in=row_ids)
        if len(payments) != len(row_ids):
            self.message_user(
                request,
                _("Could not find all payments, aborting!"),
                level=messages.ERROR,
            )
            return redirect("admin:froide_payment_payment_changelist")

        for payment in payments:
            row = row_map[payment.id]

            if row.get("Datum"):
                date = dateutil.parser.parse(row["Datum"], dayfirst=True)
                date = timezone.make_aware(date)
            else:
                date = dateutil.parser.parse(payment.attrs.processing)

            if row.get("Mandats-ID"):
                payment.attrs.mandats_id = row["Mandats-ID"]
                payment.save()

            if row["failed"].strip():
                payment.captured_amount = Decimal(0.0)
                payment.received_amount = Decimal(0.0)
                payment.change_status(PaymentStatus.REJECTED)
                payment.save()
            elif row["captured"].strip():
                payment.captured_amount = payment.total
                payment.received_amount = payment.total
                payment.received_timestamp = date
                payment.change_status(PaymentStatus.CONFIRMED)
                payment.save()
            order = payment.order
            if order.is_recurring:
                # Store mandats_id with customer for future reference
                subscription = order.subscription
                customer = subscription.customer
                customer_data = customer.data
                customer_data["mandats_id"] = payment.attrs.mandats_id
                customer.custom_data = json.dumps(customer_data)
                customer.save()

        return redirect("admin:froide_payment_payment_changelist")

    def send_lastschrift_mail(self, request, queryset):
        # Check that the user has change permission for the actual model
        if not request.method == "POST":
            raise PermissionDenied
        if not self.has_change_permission(request):
            raise PermissionDenied

        if request.POST.get("note", None) is not None:
            note = request.POST.get("note", "")

            mandate_sent = str(timezone.now().isoformat())

            mandate_qs = queryset.filter(extra_data__contains='"mandats_id":').exclude(
                extra_data__contains='"mandate_sent":'
            )
            mandate_qs = mandate_qs.select_related("order")
            count = 0
            for payment in mandate_qs:
                send_lastschrift_mail(payment, note=note)
                payment.attrs.mandate_sent = mandate_sent
                payment.save()
                count += 1

            self.message_user(request, _("%d mails sent." % count))
            return None

        select_across = request.POST.get("select_across", "0") == "1"
        context = {
            "opts": self.model._meta,
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            "queryset": queryset,
            "select_across": select_across,
        }

        # Display the confirmation page
        return TemplateResponse(
            request, "froide_payment/admin/admin_lastschrift_email.html", context
        )

    send_lastschrift_mail.short_description = _("Send lastschrift mail to users")

    def convert_lastschrift_to_sepa(self, request, payment_id):
        from payments.core import provider_factory

        from .utils import lastschrift_sepa_mail

        SEPA = "sepa"
        provider = provider_factory(SEPA)

        if lastschrift_sepa_mail is None:
            raise PermissionDenied
        if not request.method == "POST":
            raise PermissionDenied
        if not self.has_change_permission(request):
            raise PermissionDenied

        try:
            payment = Payment.objects.get(id=payment_id)
        except Payment.DoesNotExist:
            return redirect("/")

        order = payment.order
        owner_name = ""
        iban = ""
        try:
            owner_name = payment.attrs.owner
            iban = payment.attrs.iban
        except KeyError:
            if order.customer:
                customer_data = order.customer.data
                owner_name = customer_data.get("owner", order.get_full_name())
                iban = customer_data.get("iban", "")

        # Mark this payment as CANCELED again => not happening anymore
        payment.status = PaymentStatus.CANCELED
        payment.save()

        if order.is_recurring:
            subscription = order.subscription
            plan = subscription.plan
            if plan.provider != SEPA:
                new_plan = provider.get_or_create_plan(
                    plan.name, plan.category, plan.amount, plan.interval
                )
                subscription.plan = new_plan
                subscription.save()

        new_payment = order.get_or_create_payment(SEPA, request=request)
        new_payment.attrs.iban = iban
        new_payment.attrs.owner = owner_name
        new_payment.save()

        lastschrift_sepa_mail.send(
            email=payment.billing_email,
            context={"first_name": payment.billing_first_name, "order": order},
            priority=True,
        )

        return redirect(order.get_absolute_payment_url(SEPA))


class ProductAdmin(admin.ModelAdmin):
    pass


admin.site.register(Plan, PlanAdmin)
admin.site.register(Customer, CustomerAdmin)
admin.site.register(Subscription, SubscriptionAdmin)
admin.site.register(Order, OrderAdmin)
admin.site.register(Payment, PaymentAdmin)
admin.site.register(Product, ProductAdmin)
