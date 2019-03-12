from decimal import Decimal
import json

import stripe

from django.conf import settings
from django.http import HttpResponse

from payments.forms import PaymentForm
from payments.stripe import StripeProvider
from payments import PaymentStatus, RedirectNeeded, get_payment_model

from .forms import SourcePaymentForm


class StripeWebhookMixin():
    def decode_webhook_request(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        event = None

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.signing_secret
            )
        except ValueError as e:
            return None
        except stripe.error.SignatureVerificationError as e:
            return None
        return event.to_dict()

    def get_token_from_request(self, request=None, payment=None):
        '''
        Extract payment token from webhook
        via payment intent's id == payment.transaction_id
        '''
        event_dict = self.decode_webhook_request(request)
        if event_dict is None:
            return None
        intent = event_dict['data']['object']
        Payment = get_payment_model()
        try:
            payment = Payment.objects.get(
                transaction_id=intent['id']
            )
        except Payment.DoesNotExist:
            return None
        return payment.token

    def process_data(self, payment, request):
        event_dict = self.decode_webhook_request(request)
        event_type = event_dict['type']

        method_name = event_type.replace('.', '_')
        method = getattr(self, method_name)
        result = method(payment, request, event_dict)
        if result is not None:
            return result

        return HttpResponse(status=201)


class StripeIntentProvider(StripeWebhookMixin, StripeProvider):
    form_class = PaymentForm

    def __init__(self, **kwargs):
        self.signing_secret = kwargs.pop('signing_secret')
        super().__init__(**kwargs)

    def get_form(self, payment, data=None):
        if payment.status == PaymentStatus.WAITING:
            payment.change_status(PaymentStatus.INPUT)

        form = self.form_class(
            data=data, payment=payment, provider=self
        )
        if data is not None:
            if form.is_valid():
                form.save()
                raise RedirectNeeded(payment.get_success_url())

        if payment.transaction_id:
            intent = stripe.PaymentIntent.retrieve(payment.transaction_id)
        else:
            intent = stripe.PaymentIntent.create(
                amount=int(payment.total * 100),
                currency=payment.currency,
                payment_method_types=['card'],
                use_stripe_sdk=True,
                statement_descriptor='{} {}'.format(
                    settings.SITE_NAME,
                    payment.order.id
                ),
                metadata={'order_id': str(payment.order.token)},
            )
            payment.transaction_id = intent.id
            payment.save()
        if intent.status == 'succeeded':
            raise RedirectNeeded(payment.get_success_url())

        form.public_key = self.public_key
        form.intent_secret = intent.client_secret

        return form

    def payment_intent_succeeded(self, payment, request, event_dict):
        intent = event_dict['data']['object']

        payment.attrs.charges = intent.charges.data
        payment.captured_amount = Decimal(intent.amount_received) / 100
        payment.change_status(PaymentStatus.CONFIRMED)

    def payment_intent_failed(self, payment, request, event_dict):
        intent = event_dict['data']['object']
        error_message = None
        if intent.get('last_payment_error'):
            error_message = intent['last_payment_error']['message']
        payment.change_status(PaymentStatus.ERROR, message=error_message)


class StripeSourceProvider(StripeProvider):
    form_class = SourcePaymentForm

    def get_form(self, payment, data=None):
        form = super().get_form(payment, data=data)
        form.public_key = self.public_key
        return form

    def charge_succeeded(self, payment, request, event_dict):
        charge = event_dict['data']['object']

        payment.attrs.charge = json.dumps(charge)
        payment.captured_amount = Decimal(charge.amount) / 100
        payment.change_status(PaymentStatus.CONFIRMED)
