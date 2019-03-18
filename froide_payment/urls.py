from django.conf.urls import url

from .views import start_payment

app_name = 'froide_payment'

TOKEN_PATTERN = '(?P<token>[^/]+)'

urlpatterns = [
    url(r'^%s/payment/(?P<variant>[-\w]+)/$' % (TOKEN_PATTERN,),
        start_payment, name='start-payment'),
]
