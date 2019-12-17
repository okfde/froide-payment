from decimal import Decimal
import json
import logging

from django.conf import settings
from django.shortcuts import redirect
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.text import slugify
from django.utils import timezone

import requests
import pytz

from payments.paypal import PaypalProvider as OriginalPaypalProvider
from payments import RedirectNeeded

from ..models import PaymentStatus, Plan, Product, Subscription, Payment

logger = logging.getLogger(__name__)


def utcisoformat(dt):
    tz = timezone.get_default_timezone()
    # Convert datetime to UTC, remove microseconds, remove timezone
    no_us_dt = dt.replace(microsecond=0)
    return tz.localize(no_us_dt).astimezone(pytz.utc).replace(
        tzinfo=None
    ).isoformat() + 'Z'


class PaypalProvider(OriginalPaypalProvider):
    provider_name = 'paypal'

    def __init__(self, **kwargs):
        self.webhook_id = kwargs.pop('webhook_id')
        super().__init__(**kwargs)

    def get_form(self, payment, data=None):
        '''
        Converts *payment* into a form suitable for Django templates.
        '''

        order = payment.order
        if not order.is_recurring:
            return super().get_form(payment, data=data)
        return self.setup_subscription(payment, data=data)

    def process_data(self, payment, request):
        order = payment.order
        if not order.is_recurring:
            return self.super_process_data(payment, request)
        return self.finalize_subscription(payment)

    def execute_payment(self, payment, payer_id):
        post = {'payer_id': payer_id}
        links = self._get_links(payment)
        if 'execute' not in links:
            return
        execute_url = links['execute']['href']
        return self.post(payment, execute_url, data=post)

    def super_process_data(self, payment, request):
        success_url = payment.get_success_url()
        if 'token' not in request.GET:
            return HttpResponseForbidden('FAILED')
        payer_id = request.GET.get('PayerID')
        if not payer_id:
            if payment.status != PaymentStatus.CONFIRMED:
                payment.change_status(PaymentStatus.REJECTED)
                return redirect(payment.get_failure_url())
            else:
                return redirect(success_url)
        executed_payment = self.execute_payment(payment, payer_id)
        if executed_payment is None:
            return redirect(success_url)
        self.set_response_links(payment, executed_payment)
        payment.attrs.payer_info = executed_payment['payer']['payer_info']
        if self._capture:
            payment.captured_amount = payment.total
            payment.change_status(PaymentStatus.CONFIRMED)
        else:
            payment.change_status(PaymentStatus.PREAUTH)
        return redirect(success_url)

    def _get_access_token(self):
        headers = {
            'Accept': 'application/json',
            'Accept-Language': 'en_US'
        }
        post = {'grant_type': 'client_credentials'}
        response = requests.post(
            self.oauth2_url, data=post,
            headers=headers,
            auth=(self.client_id, self.secret)
        )
        response.raise_for_status()
        data = response.json()
        return '%s %s' % (data['token_type'], data['access_token'])

    def get_api(self, url, params):
        access_token = self._get_access_token()
        headers = {
            'Content-Type': 'application/json',
            'Authorization': access_token
        }
        response = requests.get(url, params=params, headers=headers)
        return response.json()

    def post_api(self, url, data):
        access_token = self._get_access_token()
        headers = {
            'Content-Type': 'application/json',
            'Authorization': access_token
        }
        response = requests.post(url, json=data, headers=headers)
        try:
            data = response.json()
        except ValueError:
            data = {}
        if 400 <= response.status_code <= 500:
            logger.debug(data)
            message = 'Paypal error'
            if response.status_code == 400:
                error_data = response.json()
                logger.warning(message, extra={
                    'response': error_data,
                    'status_code': response.status_code})
                message = error_data.get('message', message)
            else:
                logger.warning(
                    message, extra={'status_code': response.status_code})
            raise ValueError(message)
        return data

    def handle_webhook(self, request):
        if 'PAYPAL-TRANSMISSION-ID' not in request.headers:
            return HttpResponse(status=400)

        try:
            data = json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return HttpResponse(status=400)

        if not self.verify_webhook(request, data):
            return HttpResponse(status=400)
        logger.info('Paypal webhook: %s', data)
        method_name = data['event_type'].replace('.', '_').lower()
        method = getattr(self, 'webhook_%s' % method_name, None)
        if method is None:
            return HttpResponse(status=204)

        method(request, data)

        return HttpResponse(status=204)

    def webhook_billing_subscription_activated(self, request, data):
        resource = data['resource']
        sub_remote_reference = resource['id']
        try:
            subscription = Subscription.objects.get(
                remote_reference=sub_remote_reference
            )
        except Subscription.DoesNotExist:
            return
        subscription.active = True
        subscription.save()
        # last payment is not always in billing info
        try:
            # Get the latest payment of subscription
            payment = Payment.objects.filter(
                order__subscription=subscription,
            )[0]
        except IndexError:
            return
        payment.attrs.paypal_resource = resource
        payment.captured_amount = Decimal(payment.total)
        payment.change_status(PaymentStatus.CONFIRMED)

    def webhook_payment_sale_completed(self, request, data):
        resource = data['resource']
        payment_reference = resource['parent_payment']
        try:
            payment = Payment.objects.get(
                transaction_id=payment_reference
            )
        except Payment.DoesNotExist:
            return
        payment.attrs.paypal_resource = resource
        payment.captured_amount = Decimal(payment.total)
        fee = Decimal(resource.get('transaction_fee', {}).get('value', '0.0'))
        payment.received_amount = Decimal(payment.total) - fee
        payment.save()

    def verify_webhook(self, request, data):
        def get_header(key):
            return request.headers.get(key, '')

        verify_data = {
            "transmission_id": get_header('PAYPAL-TRANSMISSION-ID'),
            "transmission_time": get_header('PAYPAL-TRANSMISSION-TIME'),
            "cert_url": get_header('PAYPAL-CERT-URL'),
            "auth_algo": get_header('PAYPAL-AUTH-ALGO'),
            "transmission_sig": get_header('PAYPAL-TRANSMISSION-SIG'),
            "webhook_id": self.webhook_id,
            "webhook_event": data
        }
        verify_url = self.endpoint + (
            '/v1/notifications/verify-webhook-signature'
        )
        response = self.post_api(verify_url, verify_data)
        return response['verification_status'] == 'SUCCESS'

    def finalize_subscription(self, payment):
        order = payment.order

        if not order.is_fully_paid():
            self.capture_subscription_order(order, payment=payment)
        return redirect(payment.get_success_url())

    def synchronize_orders(self, subscription):
        list_url = '{e}/v1/billing/subscriptions/{s}/transactions'.format(
            e=self.endpoint,
            s=subscription.remote_reference
        )
        params = {
            'start_time': utcisoformat(subscription.last_date),
            'end_time': utcisoformat(subscription.last_date),
        }
        self.get_api(list_url, params)

    def cancel_subscription(self, subscription):
        cancel_url = '{e}/v1/billing/subscriptions/{sub_id}/cancel'.format(
            e=self.endpoint,
            sub_id=subscription.remote_reference
        )
        cancel_data = {
            'reason': 'unknown'

        }
        try:
            self.post_api(cancel_url, cancel_data)
        except ValueError:
            # canceling failed
            return False

        subscription.active = False
        subscription.remote_reference = ''
        subscription.save()
        return True

    def capture_subscription_order(self, order, payment=None):
        subscription = order.subscription
        if payment is None:
            payment = order.get_or_create_payment(self.provider_name)
        capture_url = '{e}/v1/billing/subscriptions/{sub_id}/capture'.format(
            e=self.endpoint,
            sub_id=subscription.remote_reference
        )
        capture_data = {
            'note': subscription.plan.name,
            'capture_type': 'OUTSTANDING_BALANCE',
            'amount': {
                'currency_code': order.currency,
                'value': str(order.total_gross)
            }

        }
        try:
            response = self.post_api(capture_url, capture_data)
        except ValueError:
            # can't capture
            return
        if response['status'] in ('COMPLETED', 'PARTIALLY_REFUNDED'):
            payment.transaction_id = response['id']
            amount = response['amount_with_breakdown']['gross_amount']['value']
            payment.captured_amount = Decimal(amount)
            payment.change_status(PaymentStatus.CONFIRMED)
        elif response['status'] == 'PENDING':
            payment.change_status(PaymentStatus.PENDING)
        elif response['status'] == 'REFUNDED':
            payment.change_status(PaymentStatus.REFUNDED)
        else:
            payment.change_status(PaymentStatus.REJECTED)

    def setup_subscription(self, payment, data=None):
        order = payment.order
        subscription = order.subscription
        plan = subscription.plan
        customer = subscription.customer
        if subscription.remote_reference:
            pass
        else:
            return_url = self.get_return_url(payment)
            subscription_data = {
                "plan_id": plan.remote_reference,
                "subscriber": {
                    "name": {
                        "given_name": customer.first_name,
                        "surname": customer.last_name
                    },
                    "email_address": customer.user_email
                },
                "application_context": {
                    "brand_name": settings.SITE_NAME,
                    "locale": settings.LANGUAGE_CODE,
                    "shipping_preference": "NO_SHIPPING",
                    "user_action": "SUBSCRIBE_NOW",
                    "payment_method": {
                        "payer_selected": "PAYPAL",
                        "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED"
                    },
                    "return_url": return_url,
                    "cancel_url": return_url,
                }
            }
            subscription_url = self.endpoint + '/v1/billing/subscriptions'
            data = self.post_api(subscription_url, subscription_data)
            subscription.remote_reference = data['id']
            subscription.save()
            approve_urls = [
                l['href'] for l in data['links']
                if l['rel'] == 'approve'
            ]
            if approve_urls:
                raise RedirectNeeded(approve_urls[0])

    def get_or_create_product(self, category):
        try:
            product = Product.objects.get(
                category=category,
                provider=self.provider_name
            )
        except Product.DoesNotExist:
            home_url = settings.SITE_URL
            if 'localhost' in home_url:
                home_url = 'http://example.org'
            product_data = {
                "name": category,
                "type": "SERVICE",
                "home_url": home_url,
            }
            product_url = self.endpoint + '/v1/catalogs/products'
            data = self.post_api(product_url, product_data)

            product = Product.objects.create(
                name='{provider} {category}'.format(
                    provider=self.provider_name,
                    category=category
                ),
                category=category,
                provider=self.provider_name,
                remote_reference=data['id']
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
            plan_data = {
                "product_id": product.remote_reference,
                "name": plan_name,
                "description": plan_name,
                "billing_cycles": [{
                    "frequency": {
                        "interval_unit": "MONTH",
                        "interval_count": month_interval,
                    },
                    "tenure_type": "REGULAR",
                    "total_cycles": 0,
                    "sequence": 1,
                    "pricing_scheme": {
                        "fixed_price": {
                            "value": str(amount),
                            "currency_code": settings.DEFAULT_CURRENCY
                        }
                    },
                }],
                "payment_preferences": {
                    "auto_bill_outstanding": True,
                    "setup_fee_failure_action": "CONTINUE",
                    "payment_failure_threshold": 0
                },
            }
            plan_url = self.endpoint + '/v1/billing/plans'
            data = self.post_api(plan_url, plan_data)

            plan = Plan.objects.create(
                name=plan_name,
                slug=slugify(plan_name),
                category=category,
                amount=amount,
                interval=month_interval,
                amount_year=amount * Decimal(12 / month_interval),
                provider=self.provider_name,
                remote_reference=data['id'],
                product=product
            )
        return plan
