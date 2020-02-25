import csv
from decimal import Decimal
from io import StringIO
import json

import dateutil.parser

from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.utils import timezone
from django.conf.urls import url
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import ugettext_lazy as _
from django.template.response import TemplateResponse

from .models import (
    Plan, Customer, Subscription, Payment, Order, Product,
    PaymentStatus
)
from .utils import (
    dicts_to_csv_response, send_lastschrift_mail
)


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
        'customer', 'plan', 'created', 'next_date',
        'active', 'canceled'
    )
    date_hierarchy = 'created'
    list_filter = (
        'active',
        'plan__provider',
        'plan__interval',
        'plan__amount',
        'plan__amount_year',
        'canceled',
    )
    search_fields = (
        'customer__user_email',
        'customer__last_name', 'customer__first_name',
        'remote_reference',
    )
    actions = ['create_recurring_order']

    def create_recurring_order(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied

        count = 0
        for sub in queryset:
            res = sub.create_recurring_order()
            if res:
                count += 1

        self.message_user(request, _("%d recurring orders created." % count))
    create_recurring_order.short_description = _(
        'Force create next recurring order'
    )


class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'user_email', 'first_name', 'last_name', 'created', 'user',
        'subscription', 'total_net'
    )
    date_hierarchy = 'created'
    raw_id_fields = ('user', 'customer', 'subscription',)
    search_fields = (
        'user_email', 'last_name', 'first_name',
        'remote_reference'
    )


class PaymentAdmin(admin.ModelAdmin):
    raw_id_fields = ('order',)
    date_hierarchy = 'created'
    list_display = (
        'billing_email', 'status', 'variant',
        'created', 'modified', 'total', 'captured_amount'
    )
    list_filter = ('variant', 'status')
    search_fields = ('transaction_id', 'billing_email', 'billing_last_name')

    actions = ['export_lastschrift', 'send_lastschrift_mail']

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
                    payment.order.get_service_label(),
                    payment.id
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

            if row.get('Datum'):
                date = dateutil.parser.parse(row['Datum'], dayfirst=True)
                date = timezone.make_aware(date)
            else:
                date = dateutil.parser.parse(
                    payment.attrs.processing
                )

            if row.get('Mandats-ID'):
                payment.attrs.mandats_id = row['Mandats-ID']
                payment.save()

            if row['failed'].strip():
                payment.captured_amount = Decimal(0.0)
                payment.received_amount = Decimal(0.0)
                payment.change_status(PaymentStatus.REJECTED)
            elif row['captured'].strip():
                payment.captured_amount = payment.total
                payment.received_amount = payment.total
                payment.received_timestamp = date
                payment.change_status(PaymentStatus.CONFIRMED)
            order = payment.order
            if order.is_recurring:
                # Store mandats_id with customer for future reference
                subscription = order.subscription
                customer = subscription.customer
                customer_data = customer.data
                customer_data['mandats_id'] = payment.attrs.mandats_id
                customer.custom_data = json.dumps(customer_data)
                customer.save()

        return redirect('admin:froide_payment_payment_changelist')

    def send_lastschrift_mail(self, request, queryset):
        # Check that the user has change permission for the actual model
        if not request.method == 'POST':
            raise PermissionDenied
        if not self.has_change_permission(request):
            raise PermissionDenied

        if request.POST.get('note', None) is not None:
            note = request.POST.get('note', '')

            mandate_sent = str(timezone.now().isoformat())

            mandate_qs = queryset.filter(
                extra_data__contains='"mandats_id":'
            ).exclude(
                extra_data__contains='"mandate_sent":'
            )
            mandate_qs = mandate_qs.select_related('order')
            count = 0
            for payment in mandate_qs:
                send_lastschrift_mail(payment, note=note)
                payment.attrs.mandate_sent = mandate_sent
                payment.save()
                count += 1

            self.message_user(request, _("%d mails sent." % count))
            return None

        select_across = request.POST.get('select_across', '0') == '1'
        context = {
            'opts': self.model._meta,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'queryset': queryset,
            'select_across': select_across
        }

        # Display the confirmation page
        return TemplateResponse(
            request, 'froide_payment/admin/admin_lastschrift_email.html',
            context)
    send_lastschrift_mail.short_description = _(
        "Send lastschrift mail to users"
    )


class ProductAdmin(admin.ModelAdmin):
    pass


admin.site.register(Plan, PlanAdmin)
admin.site.register(Customer, CustomerAdmin)
admin.site.register(Subscription, SubscriptionAdmin)
admin.site.register(Order, OrderAdmin)
admin.site.register(Payment, PaymentAdmin)
admin.site.register(Product, ProductAdmin)
