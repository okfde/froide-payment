from decimal import Decimal
import json
import logging

import stripe

from django.conf import settings
from django.shortcuts import redirect
from django.http import HttpResponse

from payments.forms import PaymentForm
from payments.stripe import StripeProvider
from payments.core import BasicProvider
from payments import RedirectNeeded, get_payment_model

from .models import PaymentStatus
from .forms import SourcePaymentForm

logger = logging.getLogger(__name__)


class StripeWebhookMixin():
    def __init__(self, **kwargs):
        self.signing_secret = kwargs.pop('signing_secret', '')
        super().__init__(**kwargs)

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
        obj = event_dict['data']['object']
        Payment = get_payment_model()
        try:
            payment = Payment.objects.get(
                transaction_id=obj['id'],
            )
        except Payment.DoesNotExist:
            return None
        return payment.token

    def process_data(self, payment, request):
        if payment.variant != self.provider_name:
            # This payment reached the wrong provider implementation endpoint
            return HttpResponse(status=201)

        event_dict = self.decode_webhook_request(request)
        event_type = event_dict['type']

        method_name = event_type.replace('.', '_')
        method = getattr(self, method_name, None)
        if method is None:
            return HttpResponse(status=201)

        result = method(payment, request, event_dict)
        if result is not None:
            return result

        return HttpResponse(status=201)


def get_statement_descriptor(payment):
    return '{} {}'.format(
            settings.SITE_NAME,
            payment.order.id
        )


class StripeIntentProvider(StripeWebhookMixin, StripeProvider):
    form_class = PaymentForm
    provider_name = 'creditcard'

    def update_status(self, payment):
        if payment.status not in (PaymentStatus.PENDING, PaymentStatus.INPUT):
            return
        if not payment.transaction_id:
            return
        intent = stripe.PaymentIntent.retrieve(payment.transaction_id)
        if intent.status == 'succeeded':
            payment.change_status(PaymentStatus.CONFIRMED)
            return True

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
                statement_descriptor=get_statement_descriptor(payment),
                metadata={'order_id': str(payment.order.token)},
            )
            payment.transaction_id = intent.id
            payment.save()
        if intent.status == 'succeeded':
            payment.change_status(PaymentStatus.CONFIRMED)
            raise RedirectNeeded(payment.get_success_url())

        form.public_key = self.public_key
        form.intent_secret = intent.client_secret

        return form

    def payment_intent_succeeded(self, payment, request, event_dict):
        logger.info('Creditcard Webhook: Payment intent succeeded: %d',
                    payment.id)
        intent = event_dict['data']['object']

        payment.attrs.charges = intent.charges.data
        payment.captured_amount = Decimal(intent.amount_received) / 100
        payment.change_status(PaymentStatus.CONFIRMED)

    def payment_intent_failed(self, payment, request, event_dict):
        logger.info('Creditcard Webhook: Payment intent failed: %d',
                    payment.id)
        intent = event_dict['data']['object']
        error_message = None
        if intent.get('last_payment_error'):
            error_message = intent['last_payment_error']['message']
        payment.change_status(PaymentStatus.ERROR, message=error_message)


class StripeSourceProvider(StripeProvider):
    form_class = SourcePaymentForm
    provider_name = 'sepa'

    def get_form(self, payment, data=None):
        form = super().get_form(payment, data=data)
        form.public_key = self.public_key
        return form

    def charge_succeeded(self, payment, request, event_dict):
        charge = event_dict['data']['object']

        payment.attrs.charge = json.dumps(charge)
        payment.captured_amount = Decimal(charge.amount) / 100
        payment.change_status(PaymentStatus.CONFIRMED)


class StripeSofortProvider(StripeWebhookMixin, StripeProvider):
    provider_name = 'sofort'

    def update_status(self, payment):
        if payment.status not in (PaymentStatus.PENDING, PaymentStatus.INPUT):
            return
        if not payment.transaction_id:
            return
        intent = stripe.PaymentIntent.retrieve(payment.transaction_id)
        if intent.status == 'succeeded':
            payment.change_status(PaymentStatus.CONFIRMED)
            return True

    def get_form(self, payment, data=None):
        if payment.transaction_id:
            raise RedirectNeeded(payment.get_success_url())
        else:
            try:
                source = stripe.Source.create(
                    type='sofort',
                    amount=int(payment.total * 100),
                    currency=payment.currency,
                    statement_descriptor=get_statement_descriptor(payment),
                    redirect={
                        'return_url': self.get_return_url(payment),
                    },
                    sofort={
                        'country': 'DE',
                    },
                )
                payment.transaction_id = source.id
                payment.change_status(PaymentStatus.INPUT)
            except stripe.error.StripeError as e:
                payment.change_status(PaymentStatus.ERROR)
                # charge_id = e.json_body['error']['charge']
                raise RedirectNeeded(payment.get_failure_url())
        if source.status == 'chargeable':
            self.charge_source(payment, source)
            raise RedirectNeeded(payment.get_success_url())
        else:
            raise RedirectNeeded(source.redirect['url'])

    def get_token_from_request(self, request=None, payment=None):
        if request.method == 'GET':
            # Redirect not webhook
            source_id = request.GET.get('source')
            if source_id is None:
                return None
            Payment = get_payment_model()
            try:
                payment = Payment.objects.get(
                    transaction_id=source_id,
                )
            except Payment.DoesNotExist:
                return None
            return payment.token
        return super().get_token_from_request(request=request, payment=payment)

    def process_data(self, payment, request):
        if request.method == 'GET':
            # Redirect (not webhook)
            try:
                source_id = request.GET['source']
                client_secret = request.GET['client_secret']
            except KeyError:
                payment.change_status(PaymentStatus.ERROR)
                return redirect(payment.get_failure_url())
            try:
                source = stripe.Source.retrieve(
                    source_id, client_secret=client_secret
                )
            except stripe.error.StripeError as e:
                payment.change_status(PaymentStatus.ERROR)
                return redirect(payment.get_failure_url())
            if source.status in ('canceled', 'failed'):
                payment.change_status(PaymentStatus.REJECTED)
                return redirect(payment.get_failure_url())
            # Charging takes place in webhook
            payment.change_status(PaymentStatus.PENDING)
            return redirect(payment.get_success_url())
        # Process web hook
        logger.info('Incoming Sofort Webhook')
        return super().process_data(payment, request)

    def charge_source(self, payment, source):
        try:
            charge = stripe.Charge.create(
                amount=int(payment.total * 100),
                currency=payment.currency,
                source=source.id,
            )
        except stripe.error.StripeError as e:
            payment.change_status(PaymentStatus.ERROR)
            raise RedirectNeeded(payment.get_failure_url())

        payment.transaction_id = charge.id
        payment.save()

    def source_chargeable(self, payment, request, event_dict):
        logger.info('Sofort Webhook: source chargeable: %d', payment.id)
        source = event_dict['data']['object']
        if not payment.transaction_id.startswith(source.id):
            return
        self.charge_source(payment, source)

    def charge_succeeded(self, payment, request, event_dict):
        logger.info('Sofort Webhook: charge succeeded: %d', payment.id)
        charge = event_dict['data']['object']
        payment.attrs.charge = json.dumps(charge)
        payment.captured_amount = Decimal(charge.amount) / 100
        payment.change_status(PaymentStatus.CONFIRMED)

    def charge_failed(self, payment, request, event_dict):
        logger.info('Sofort Webhook: charge failed: %d', payment.id)
        charge = event_dict['data']['object']
        payment.attrs.charge = json.dumps(charge)
        payment.captured_amount = Decimal(charge.amount) / 100
        payment.change_status(PaymentStatus.REJECTED)


class LastschriftProvider(BasicProvider):
    provider_name = 'lastschrift'

    def get_form(self, payment, data=None):
        '''
        Lastschrift gets stored and processed
        '''
        if payment.status == PaymentStatus.WAITING:
            payment.change_status(PaymentStatus.INPUT)

        iban = None
        if payment.order.customer:
            customer = payment.order.customer
            iban = customer.data.get('iban', None)

        if iban is not None:
            if payment.status == PaymentStatus.INPUT:
                payment.change_status(PaymentStatus.PENDING)
            raise RedirectNeeded(payment.get_success_url())
