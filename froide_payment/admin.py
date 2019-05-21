from django.contrib import admin

from .models import Plan, Customer, Subscription, Payment, Order


class PlanAdmin(admin.ModelAdmin):
    prepopulated_fields = {'slug': ('name',)}
    list_display = (
        'name', 'category', 'display_amount',
        'interval', 'created'
    )
    list_filter = ('category',)

    def display_amount(self, obj):
        return '{} {}'.format(obj.amount.amount, obj.amount.currency)


class CustomerAdmin(admin.ModelAdmin):
    raw_id_fields = ('user',)


class SubscriptionAdmin(admin.ModelAdmin):
    raw_id_fields = ('customer',)


class OrderAdmin(admin.ModelAdmin):
    raw_id_fields = ('user', 'customer', 'subscription',)


class PaymentAdmin(admin.ModelAdmin):
    raw_id_fields = ('order',)
    list_display = ('billing_email', 'status', 'variant', 'token')


admin.site.register(Plan, PlanAdmin)
admin.site.register(Customer, CustomerAdmin)
admin.site.register(Subscription, SubscriptionAdmin)
admin.site.register(Order, OrderAdmin)
admin.site.register(Payment, PaymentAdmin)
