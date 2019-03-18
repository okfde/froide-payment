# Froide payment

A Django app that allows running payment campaigns on FOI requests.


## Configure Stripe Webhooks

Include `payments.urls` in root URL pattern.

```python
urlpatterns = [
    ...
    url(r'^payments/', include('payments.urls')),
    ...
]
```

### Webhook for Credit Card Payments via Payment Intents

Configure these event types:

- `payment_intent.payment_failed`
- `payment_intent.succeeded`

Use this URL on your domain:

```
/payments/process/creditcard/
```

### Webhook for Sofort Payments

Configure these event types:

- `charge.succeeded`
- `charge.failed`
- `source.chargeable`
- `source.failed`

Use this URL on your domain:

```
/payments/process/sofort/
```


## Configure Payment variants

```python
PAYMENT_VARIANTS = {
    # 'default': ('payments.dummy.DummyProvider', {})
    'creditcard': ('froide_payment.provider.StripeIntentProvider', {
        # Test API keys
        'public_key': '',
        'secret_key': '',
        # separate Webhook signing secret
        'signing_secret': '',
    }),
# Disabled, not tested
#    'sepa': ('froide_payment.provider.StripeSourceProvider', {
#        # Test API keys
#        'public_key': '',
#        'secret_key': '',
#        # separate Webhook signing secret
#        'signing_secret': '',
#    }),
    'paypal': ('payments.paypal.PaypalProvider', {
        'client_id': '',
        'secret': '',
        'endpoint': '',
        'capture': True
    }),
    'sofort': ('froide_payment.provider.StripeSofortProvider', {
        # Test API keys
        'public_key': '',
        'secret_key': '',
        # separate Webhook signing secret
        'signing_secret': '',
    }),
}
```
