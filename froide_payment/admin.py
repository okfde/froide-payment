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
    search_fields = (
        'customer__user_email',
        'customer__last_name', 'customer__first_name',
    )


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
