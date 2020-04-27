from datetime import datetime
from decimal import Decimal
import json
import logging

import pytz
import stripe

from django.conf import settings
from django.shortcuts import redirect
from django.http import HttpResponse, JsonResponse
from django.utils.text import slugify
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from payments.forms import PaymentForm
from payments.stripe import StripeProvider
from payments import RedirectNeeded, get_payment_model

from ..signals import subscription_activated, subscription_deactivated
from ..models import (
    PaymentStatus, Plan, Product, Subscription, Order, Payment
)
from ..forms import SEPAPaymentForm

from .utils import CancelInfo

logger = logging.getLogger(__name__)


def convert_utc_timestamp(timestamp):
    tz = timezone.get_current_timezone()
    utc_dt = datetime.utcfromtimestamp(timestamp).replace(
        tzinfo=pytz.utc
    )
    return tz.normalize(utc_dt.astimezone(tz))


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

        # Check if this provider handles this callback
        payment_method_details = obj.get('payment_method_details', None)
        if payment_method_details:
            payment_method_type = payment_method_details.get('type')
            if payment_method_type != self.stripe_payment_method_type:
                return False
        else:
            return False

        payment = self.get_payment_by_id(obj['id'])
        if payment is None:
            return None
        return payment.token

    def get_payment_by_id(self, transaction_id):
        Payment = get_payment_model()
        try:
            return Payment.objects.get(
                transaction_id=transaction_id,
            )
        except Payment.DoesNotExist:
            return None

    def get_balance_transaction(self, txn_id):
        if not txn_id:
            return None
        try:
            bt = stripe.BalanceTransaction.retrieve(txn_id)
        except stripe.error.StripeError as e:
            return None
        return bt

    def process_data(self, payment, request):
        if payment.variant != self.provider_name:
            # This payment reached the wrong provider implementation endpoint
            return HttpResponse(status=204)
        return self.handle_webhook(request)

    def handle_webhook(self, request):
        event_dict = self.decode_webhook_request(request)
        if event_dict is None:
            # Webhook likely not for this endpoint (failed due to signing key)
            return HttpResponse(status=204)
        event_type = event_dict['type']
        obj = event_dict['data']['object']

        method_name = event_type.replace('.', '_')
        method = getattr(self, method_name, None)
        if method is None:
            return HttpResponse(status=204)

        result = method(request, obj)
        if result is not None:
            return result

        return HttpResponse(status=201)


class StripeSubscriptionMixin:

    def get_cancel_info(self, subscription):
        return CancelInfo(
            True,
            _('You can cancel your credit card subscription.')
        )

    def cancel_subscription(self, subscription):
        if not subscription.remote_reference:
            return False
        logger.info('Stripe cancel subscription: %s', subscription.id)
        try:
            stripe_sub = stripe.Subscription.delete(
                subscription.remote_reference
            )
        except stripe.error.StripeError as e:
            logger.warn(
                'Stripe cancel subscription failed: %s', subscription.id)
            logger.exception(e)
            return False
        if stripe_sub.status == 'canceled':
            return True
        return False

    def get_stripe_locales(self):
        data = {
            'de': ['de-DE'],
            'en': ['en-US']
        }
        if settings.LANGUAGE_CODE in data:
            return data[settings.LANGUAGE_CODE]
        return []

    def setup_customer(self, subscription, payment_method):
        customer = subscription.customer
        if not customer.remote_reference:
            stripe_customer = stripe.Customer.create(
                email=customer.user_email,
                name=customer.get_full_name(),
                payment_method=payment_method,
                preferred_locales=self.get_stripe_locales(),
                metadata={'customer_id': customer.id}
            )
            customer.remote_reference = stripe_customer.id
            customer.save()
        else:
            stripe.PaymentMethod.attach(
                payment_method,
                customer=customer.remote_reference
            )
            stripe.Customer.modify(
                customer.remote_reference,
                invoice_settings={
                    'default_payment_method': payment_method
                }
            )

        return customer

    def get_or_create_product(self, category):
        try:
            product = Product.objects.get(
                category=category,
                provider=self.provider_name
            )
        except Product.DoesNotExist:
            stripe_product = stripe.Product.create(
                name=category,
                type='service'
            )
            product = Product.objects.create(
                name='{provider} {category}'.format(
                    provider=self.provider_name,
                    category=category
                ),
                category=category,
                provider=self.provider_name,
                remote_reference=stripe_product.id
            )
        return product

    def get_or_create_plan(self, plan_name, category, amount, month_interval):
        product = self.get_or_create_product(category)
        try:
            plan = Plan.objects.get(
                product=product,
                amount=amount,
                interval=month_interval,
                provider=self.provider_name
            )
        except Plan.DoesNotExist:
            stripe_plan = stripe.Plan.create(
                amount=int(amount * 100),  # Stripe takes cents
                currency=settings.DEFAULT_CURRENCY.lower(),
                interval='month',
                interval_count=month_interval,
                product=product.remote_reference,
                nickname=plan_name,
            )
            plan = Plan.objects.create(
                name=plan_name,
                slug=slugify(plan_name),
                category=category,
                amount=amount,
                interval=month_interval,
                amount_year=amount * Decimal(12 / month_interval),
                provider=self.provider_name,
                remote_reference=stripe_plan.id,
                product=product
            )
        return plan


def get_statement_descriptor(payment):
    return '{} {}'.format(
            settings.SITE_NAME,
            payment.order.id
        )


class StripeIntentProvider(
        StripeSubscriptionMixin, StripeWebhookMixin, StripeProvider):
    form_class = PaymentForm
    provider_name = 'creditcard'
    stripe_payment_method_type = 'card'

    def update_status(self, payment):
        if payment.status not in (PaymentStatus.PENDING, PaymentStatus.INPUT):
            return
        if not payment.transaction_id:
            return
        try:
            intent = stripe.PaymentIntent.retrieve(payment.transaction_id)
        except stripe.error.InvalidRequestError:
            # intent is not yet available
            return
        if intent.status == 'succeeded':
            payment.change_status(PaymentStatus.CONFIRMED)
            return True
        payment.change_status(PaymentStatus.PENDING)
        return False

    def process_data(self, payment, request):
        if payment.variant != self.provider_name:
            # This payment reached the wrong provider implementation endpoint
            return HttpResponse(status=204)
        if request.is_ajax():
            return self.handle_form_communication(payment, request)
        return super().process_data(payment, request)

    def handle_form_communication(self, payment, request):
        try:
            data = json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'error': ''})
        try:
            intent = self.handle_form_method(payment, data)
        except stripe.error.StripeError as e:
            # Display error on client
            return JsonResponse({'error': e.user_message})
        except ValueError as e:
            return JsonResponse({'error': str(e)})
        if intent is True:
            return JsonResponse({'success': True})
        return self.generate_intent_response(intent)

    def handle_form_method(self, payment, data):
        if 'payment_method_id' in data:
            intent = self.handle_payment_method(
                payment,
                data['payment_method_id']
            )
        elif 'payment_intent_id' in data:
            intent = stripe.PaymentIntent.confirm(
                data['payment_intent_id']
            )
        return intent

    def generate_intent_response(self, intent):
        if intent.status == 'requires_action':
            return JsonResponse({
                'requires_action': True,
                'payment_intent_client_secret': intent.client_secret,
            })
        elif intent.status == 'requires_confirmation':
            return JsonResponse({
                'requires_confirmation': True,
                'payment_intent_client_secret': intent.client_secret,
                'payment_method': intent.payment_method,
                'customer': True if intent.customer else False
            })
        elif intent.status == 'succeeded':
            # The payment didn’t need any additional actions and completed!
            # Handle post-payment fulfillment
            return JsonResponse({'success': True})
        return JsonResponse({'error': 'Invalid PaymentIntent status'})

    def handle_payment_method(self, payment, payment_method):
        order = payment.order
        if order.is_recurring:
            intent = self.setup_subscription(
                order.subscription, payment_method
            )
        else:
            intent = stripe.PaymentIntent.create(
                amount=int(payment.total * 100),
                currency=payment.currency,
                payment_method_types=[self.stripe_payment_method_type],
                use_stripe_sdk=True,
                payment_method=payment_method,
                statement_descriptor=get_statement_descriptor(payment),
                metadata={'order_id': str(payment.order.token)},
            )
        payment.transaction_id = intent.id
        payment.save()
        return intent

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

        intent = self.get_initial_intent(payment)

        if intent is not None and intent.status == 'succeeded':
            payment.change_status(PaymentStatus.CONFIRMED)
            raise RedirectNeeded(payment.get_success_url())

        if intent is not None:
            form.intent_secret = intent.client_secret
        else:
            form.intent_secret = ''
            form.action = self.get_return_url(payment)
        form.public_key = self.public_key

        return form

    def get_initial_intent(self, payment):
        intent = None
        if payment.transaction_id:
            intent = stripe.PaymentIntent.retrieve(payment.transaction_id)
        else:
            kwargs = {}
            order = payment.order
            if not order.is_recurring:
                # For non-recurring orders create payment intent directly
                intent = stripe.PaymentIntent.create(
                    amount=int(payment.total * 100),
                    currency=payment.currency,
                    payment_method_types=[self.stripe_payment_method_type],
                    use_stripe_sdk=True,
                    statement_descriptor=get_statement_descriptor(payment),
                    metadata={'order_id': str(payment.order.token)},
                    **kwargs
                )
                payment.transaction_id = intent.id
                payment.save()
        return intent

    def setup_subscription(self, subscription, payment_method):
        plan = subscription.plan
        customer = subscription.customer
        self.setup_customer(subscription, payment_method)

        if not subscription.remote_reference:
            stripe_subscription = stripe.Subscription.create(
                customer=customer.remote_reference,
                default_payment_method=payment_method,
                items=[
                    {
                        'plan': plan.remote_reference,
                    },
                ],
                expand=[
                    'latest_invoice',
                    'latest_invoice.payment_intent'
                ],
            )
        else:
            stripe_subscription = stripe.Subscription.retrieve(
                subscription.remote_reference,
                expand=[
                    'latest_invoice',
                    'latest_invoice.payment_intent'
                ],
            )
            if stripe_subscription.plan.id != plan.remote_reference:
                stripe_subscription = stripe.Subscription.modify(
                    stripe_subscription.id,
                    cancel_at_period_end=False,
                    items=[{
                        'id': stripe_subscription['items']['data'][0].id,
                        'plan': plan.remote_reference,
                    }]
                )
        subscription.remote_reference = stripe_subscription.id
        old_sub_status = subscription.active
        if stripe_subscription.status == 'active':
            subscription.active = True
        else:
            subscription.active = False
        subscription.save()
        if old_sub_status != subscription.active:
            if subscription.active:
                subscription_activated.send(sender=subscription)
            else:
                subscription_deactivated.send(sender=subscription)

        latest_invoice = stripe_subscription.latest_invoice
        subscription.attach_order_info(
            remote_reference=latest_invoice.id,
        )
        payment_intent = stripe_subscription.latest_invoice.payment_intent
        return payment_intent

    def update_payment(self, payment):
        tn_id = payment.transaction_id
        assert tn_id.startswith('pi_')
        intent = stripe.PaymentIntent.retrieve(tn_id)
        payment.captured_amount = Decimal(intent.amount_received) / 100
        charges = intent.charges.data
        for charge in charges:
            txn = self.get_balance_transaction(charge.balance_transaction)
            if txn is not None:
                payment.received_timestamp = convert_utc_timestamp(
                    charge.created
                )
                payment.received_amount = Decimal(txn.net) / 100
                break
        if intent.status == 'succeeded':
            payment.change_status(PaymentStatus.CONFIRMED)
        else:
            payment.save()

    def get_or_create_order_from_invoice(self, invoice):
        try:
            return Order.objects.get(
                remote_reference=invoice.id
            )
        except Order.DoesNotExist:
            pass
        subscription = Subscription.objects.get(
            remote_reference=invoice.subscription,
            plan__provider=self.provider_name
        )
        first_order = subscription.get_first_order()
        customer = subscription.customer
        start_dt = convert_utc_timestamp(invoice.period_start)
        end_dt = convert_utc_timestamp(invoice.period_end)
        order = Order.objects.create(
            customer=customer,
            subscription=subscription,
            user=customer.user,
            first_name=customer.first_name,
            last_name=customer.last_name,
            street_address_1=customer.street_address_1,
            street_address_2=customer.street_address_2,
            city=customer.city,
            postcode=customer.postcode,
            country=customer.country,
            user_email=customer.user_email,
            total_net=subscription.plan.amount,
            total_gross=subscription.plan.amount,
            is_donation=first_order.is_donation,
            kind=first_order.kind,
            description=first_order.description,
            service_start=start_dt,
            service_end=end_dt,
            remote_reference=invoice.id
        )
        payment = order.get_or_create_payment(
            self.provider_name
        )
        payment.transaction_id = invoice.charge
        intent = stripe.PaymentIntent.retrieve(invoice.payment_intent)

        charges = intent.charges.data
        payment.attrs.charges = charges
        payment.captured_amount = Decimal(intent.amount_received) / 100
        for charge in charges:
            txn = self.get_balance_transaction(charge.balance_transaction)
            if txn is not None:
                payment.received_amount = Decimal(txn.net) / 100
                break
        if invoice.status == 'paid':
            payment.change_status(PaymentStatus.CONFIRMED)

    # Webhook callbacks

    def payment_intent_succeeded(self, request, intent):
        logger.info('%s Webhook: Payment intent succeeded: %s',
                    self.provider_name, intent.id)

        payment = self.get_payment_by_id(intent.id)
        if payment is None:
            return

        charges = intent.charges.data
        payment.attrs.charges = charges
        payment.captured_amount = Decimal(intent.amount_received) / 100
        for charge in charges:
            txn = self.get_balance_transaction(charge.balance_transaction)
            if txn is not None:
                payment.received_timestamp = convert_utc_timestamp(
                    charge.created
                )
                payment.received_amount = Decimal(txn.net) / 100
                break
        payment.change_status(PaymentStatus.CONFIRMED)

    def payment_intent_payment_failed(self, request, intent):
        logger.info('%s Webhook: Payment intent failed: %s',
                    self.provider_name, intent.id)

        error_message = None
        if intent.get('last_payment_error'):
            error_message = intent['last_payment_error']['message']

        payment = self.get_payment_by_id(intent.id)
        if payment is None:
            return

        payment.change_status(PaymentStatus.ERROR, message=error_message)

    def invoice_upcoming(self, request, invoice):
        # Email user to check details, no invoice id yet!
        # has subscription?
        pass

    def invoice_created(self, request, invoice):
        '''
        Create order
        '''
        try:
            subscription = Subscription.objects.get(
                remote_reference=invoice.subscription,
                plan__provider=self.provider_name
            )
        except Subscription.DoesNotExist:
            # Don't know this subscription on this provider
            return
        logger.info('%s webhook invoice created for subscription %s',
                    self.provider_name, subscription.id)

        if not Order.objects.filter(remote_reference=invoice.id).exists():
            # Create order based on invoice
            subscription.create_recurring_order(
                force=True, remote_reference=invoice.id
            )

    def invoice_finalized(self, request, invoice):
        '''
        payment intent is now available
        Create payment on order
        '''
        try:
            order = Order.objects.get(
                remote_reference=invoice.id,
                subscription__plan__provider=self.provider_name
            )
        except Order.DoesNotExist:
            # Don't know this order/invoice on this provider
            return
        payment = order.get_or_create_payment(
            self.provider_name
        )
        payment.transaction_id = invoice.payment_intent
        payment.save()
        logger.info('%s webhook invoice finalized for payment %s',
                    self.provider_name, payment.id)

    def invoice_payment_action_required(self, request, invoice):
        '''
        automatic payment does not work
        send customer email with payment link
        '''
        try:
            order = Order.objects.get(
                remote_reference=invoice.id,
                subscription__plan__provider=self.provider_name
            )
        except Order.DoesNotExist:
            # Don't know this invoice!
            return
        order
        # TODO: do something

    def charge_dispute_closed(self, request, dispute):
        if dispute["status"] != "lost":
            return
        try:
            payment = Payment.objects.get(
                remote_reference=dispute['payment_intent'],
                variant=self.provider_name
            )
        except Payment.DoesNotExist:
            logger.warning("Could not find payment for lost dispute %s",
                           dispute['id'])
            return
        payment.captured_amount = Decimal('0.0')
        payment.received_amount = Decimal('0.0')
        payment.received_timestamp = None
        payment.change_status(PaymentStatus.REJECTED)


class StripeSEPAProvider(StripeIntentProvider):
    form_class = SEPAPaymentForm
    provider_name = 'sepa'
    stripe_payment_method_type = 'sepa_debit'

    def get_cancel_info(self, subscription):
        return CancelInfo(
            True,
            _('You can cancel your SEPA direct debit subscription here.')
        )

    def get_initial_intent(self, payment):
        intent = None
        if payment.transaction_id:
            intent = stripe.PaymentIntent.retrieve(payment.transaction_id)
        return intent

    def handle_form_method(self, payment, data):
        if 'iban' in data:
            form = self.form_class(
                data=data, payment=payment, provider=self,
                hidden_inputs=False
            )
            if form.is_valid():
                intent = form.save()
                return intent
            raise ValueError(
                ' '.join(
                    ' '.join(v) for v in form.errors.values()
                )
            )
        if 'success' in data:
            # confirm payment here later
            payment.change_status(PaymentStatus.PENDING)
            return True
        return None

    def create_payment_method(self, iban, owner_name, billing_email):
        try:
            return stripe.PaymentMethod.create(
                type=self.stripe_payment_method_type,
                sepa_debit={
                    "iban": iban,
                },
                billing_details={
                    "name": owner_name,
                    "email": billing_email,
                },
            )
        except stripe.error.StripeError as e:
            logger.exception(e)
            raise ValueError(e.error.code)


class StripeSofortProvider(StripeWebhookMixin, StripeProvider):
    provider_name = 'sofort'
    stripe_payment_method_type = 'sofort'

    def update_status(self, payment):
        if payment.status not in (PaymentStatus.PENDING, PaymentStatus.INPUT):
            return
        if not payment.transaction_id:
            return
        if not payment.transaction_id.startswith(('py_', 'ch_')):
            # source has not been charged yet
            return
        try:
            charge = stripe.Charge.retrieve(payment.transaction_id)
        except stripe.error.InvalidRequestError:
            # charge is not yet available
            return
        if charge.status == 'succeeded':
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

    def update_payment(self, payment):
        tn_id = payment.transaction_id
        assert tn_id.startswith(('ch_', 'py_'))
        charge = stripe.Charge.retrieve(tn_id)
        payment.captured_amount = Decimal(charge.amount) / 100
        txn = self.get_balance_transaction(charge.balance_transaction)
        if txn is not None:
            payment.received_amount = Decimal(txn.net) / 100
        payment.received_timestamp = convert_utc_timestamp(
            charge.created
        )
        if charge.status == 'succeeded':
            payment.change_status(PaymentStatus.CONFIRMED)
        else:
            payment.save()

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
        payment.change_status(PaymentStatus.PENDING)
        payment.save()

    def source_chargeable(self, request, source):
        logger.info('Sofort Webhook: source chargeable: %d', source.id)

        payment = self.get_payment_by_id(source.id)
        if payment is None:
            return

        if not payment.transaction_id.startswith(source.id):
            return
        self.charge_source(payment, source)

    def charge_succeeded(self, request, charge):
        logger.info('Sofort Webhook: charge succeeded: %d', charge.id)

        payment = self.get_payment_by_id(charge.id)
        if payment is None:
            return

        payment.attrs.charge = json.dumps(charge)
        payment.captured_amount = Decimal(charge.amount) / 100
        txn = self.get_balance_transaction(charge.balance_transaction)
        if txn is not None:
            payment.received_amount = Decimal(txn.net) / 100
            payment.received_timestamp = convert_utc_timestamp(
                charge.created
            )
        payment.change_status(PaymentStatus.CONFIRMED)

    def charge_failed(self, request, charge):
        logger.info('Sofort Webhook: charge failed: %d', charge.id)

        payment = self.get_payment_by_id(charge.id)
        if payment is None:
            return

        payment.attrs.charge = json.dumps(charge)
        payment.captured_amount = Decimal('0.0')
        payment.change_status(PaymentStatus.REJECTED)
