from django.contrib import admin

from .models import Payment, Order


class OrderAdmin(admin.ModelAdmin):
    raw_id_fields = ('user',)


class PaymentAdmin(admin.ModelAdmin):
    raw_id_fields = ('order',)
    list_display = ('billing_email', 'status', 'variant', 'token')


admin.site.register(Order, OrderAdmin)
admin.site.register(Payment, PaymentAdmin)
