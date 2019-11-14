import csv
from decimal import Decimal
from io import StringIO

from django.contrib import admin, messages
from django.utils import timezone
from django.conf.urls import url
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import ugettext_lazy as _

from .models import (
    Plan, Customer, Subscription, Payment, Order, Product,
    PaymentStatus
)
from .utils import dicts_to_csv_response


class PlanAdmin(admin.ModelAdmin):
    prepopulated_fields = {'slug': ('name',)}
    list_display = (
        'name', 'category', 'display_amount',
        'provider',
        'interval', 'created'
    )
    list_filter = ('category', 'provider')

    def display_amount(self, obj):
        return '{} {}'.format(obj.amount, settings.DEFAULT_CURRENCY)


class CustomerAdmin(admin.ModelAdmin):
    raw_id_fields = ('user',)
    list_display = (
        'user_email', 'first_name', 'last_name',
        'created',
    )
    search_fields = ('user_email', 'last_name', 'first_name',)


class SubscriptionAdmin(admin.ModelAdmin):
    raw_id_fields = ('customer',)
    list_display = (
        'customer', 'plan', 'created',
        'active',
    )
    date_hierarchy = 'created'
    list_filter = (
        'active', 'plan__interval',
        'plan__amount', 'plan__amount_year',
    )
    search_fields = (
        'customer__user_email',
        'customer__last_name', 'customer__first_name',
    )


class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'user_email', 'first_name', 'last_name', 'created', 'user',
        'subscription', 'total_net'
    )
    date_hierarchy = 'created'
    raw_id_fields = ('user', 'customer', 'subscription',)


class PaymentAdmin(admin.ModelAdmin):
    raw_id_fields = ('order',)
    date_hierarchy = 'created'
    list_display = (
        'billing_email', 'status', 'variant',
        'created', 'modified'
    )
    list_filter = ('variant', 'status')

    actions = ['export_lastschrift']

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url(r'^import-lastschrift/$',
                self.admin_site.admin_view(self.import_lastschrift_result),
                name='froide_payment-payment-import_lastschrift_result'),
        ]
        return my_urls + urls

    def export_lastschrift(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied

        def get_lastschrift_export(payment):
            data = {
                'id': str(payment.id),
                'transaction_label': 'Spende {}: {} (P{})'.format(
                    settings.SITE_NAME,
                    payment.order.description, payment.id
                ),
                'amount': str(payment.total),
                'currency': payment.currency,
                'name': ' '.join([
                    payment.billing_first_name,
                    payment.billing_last_name,
                ]),
                'iban': payment.attrs.iban,
                'failed': '',
                'captured': '',
            }

            return data

        # Only export pending lastschrift
        base_queryset = queryset.filter(
            variant='lastschrift',
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
        queryset = queryset.select_related('order')

        filename = 'lastschrift_{}.csv'.format(
            timezone.now().isoformat(timespec='minutes')
        )
        dict_generator = (
            get_lastschrift_export(payment) for payment in queryset
        )
        return dicts_to_csv_response(dict_generator, name=filename)

    def import_lastschrift_result(self, request):
        if not request.method == 'POST':
            raise PermissionDenied
        if not self.has_change_permission(request):
            raise PermissionDenied

        csv_file = request.FILES.get('file')
        csv_file = StringIO(csv_file.read().decode('utf-8'))
        reader = csv.DictReader(csv_file)
        rows = [row for row in reader]
        row_map = {int(row['id']): row for row in rows}
        row_ids = list(row_map.keys())
        payments = Payment.objects.filter(
            variant='lastschrift',
            id__in=row_ids
        )
        if len(payments) != len(row_ids):
            self.message_user(
                request, _('Could not find all payments, aborting!'),
                level=messages.ERROR
            )
            return redirect('admin:froide_payment_payment_changelist')

        for payment in payments:
            row = row_map[payment.id]
            if row['failed'].strip():
                payment.captured_amount = Decimal(0.0)
                payment.change_status(PaymentStatus.REJECTED)
            elif row['captured'].strip():
                payment.attrs.mandats_id = row['Mandats-ID']
                payment.captured_amount = payment.total
                payment.change_status(PaymentStatus.CONFIRMED)

        return redirect('admin:froide_payment_payment_changelist')


class ProductAdmin(admin.ModelAdmin):
    pass


admin.site.register(Plan, PlanAdmin)
admin.site.register(Customer, CustomerAdmin)
admin.site.register(Subscription, SubscriptionAdmin)
admin.site.register(Order, OrderAdmin)
admin.site.register(Payment, PaymentAdmin)
admin.site.register(Product, ProductAdmin)
