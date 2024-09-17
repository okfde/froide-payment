from django.urls import path

from .views import (
    order_detail,
    order_failed,
    order_success,
    start_payment,
    subscription_cancel,
    subscription_detail,
    subscription_modify,
)

app_name = "froide_payment"

urlpatterns = [
    path("subscription/<uuid:token>/", subscription_detail, name="subscription-detail"),
    path(
        "subscription/<uuid:token>/cancel/",
        subscription_cancel,
        name="subscription-cancel",
    ),
    path(
        "subscription/<uuid:token>/modify/",
        subscription_modify,
        name="subscription-modify",
    ),
    path("<uuid:token>/", order_detail, name="order-detail"),
    path("<uuid:token>/success/", order_success, name="order-success"),
    path("<uuid:token>/failed/", order_failed, name="order-failed"),
    path("<uuid:token>/payment/<slug:variant>/", start_payment, name="start-payment"),
]
