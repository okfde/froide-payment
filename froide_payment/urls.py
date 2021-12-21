from django.urls import path

from .views import (
    start_payment,
    order_detail,
    order_success,
    subscription_detail,
    subscription_cancel,
)

app_name = "froide_payment"

urlpatterns = [
    path("subscription/<uuid:token>/", subscription_detail, name="subscription-detail"),
    path(
        "subscription/<uuid:token>/cancel/",
        subscription_cancel,
        name="subscription-cancel",
    ),
    path("<uuid:token>/", order_detail, name="order-detail"),
    path("<uuid:token>/success/", order_success, name="order-success"),
    path(
        "<uuid:token>/payment/<slug:variant>/", start_payment, name="start-payment"
    ),
]
