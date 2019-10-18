from django.conf.urls import url

from .views import start_payment, order_detail, subscription_detail

app_name = 'froide_payment'

TOKEN_PATTERN = '(?P<token>[^/]+)'

urlpatterns = [
    url(r'^subscription/%s/$' % (TOKEN_PATTERN,),
        subscription_detail, name='subscription-detail'),
    url(r'^%s/$' % (TOKEN_PATTERN,),
        order_detail, name='order-detail'),
    url(r'^%s/payment/(?P<variant>[-\w]+)/$' % (TOKEN_PATTERN,),
        start_payment, name='start-payment'),
]
