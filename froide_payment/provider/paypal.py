import json
import logging
from datetime import timedelta
from datetime import timezone as tz
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

import dateutil.parser
import requests
from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from payments import PaymentError, RedirectNeeded
from payments.core import BasicProvider

from froide_payment.provider.mixins import EditableMixin

from ..models import Payment, PaymentStatus, Plan, Product, Subscription
from ..signals import (
    subscription_activated,
    subscription_canceled,
    subscription_deactivated,
)
from .utils import CancelInfo, ModifyInfo

logger = logging.getLogger(__name__)

CENTS = Decimal("0.01")


class TransactionAmounts(NamedTuple):
    amount: Decimal
    fee: Decimal


def utcisoformat(dt):
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt, timezone=tz.utc)
    return dt.replace(microsecond=0).replace(tzinfo=None).isoformat() + "Z"


class PaypalProvider(BasicProvider, EditableMixin):
    provider_name = "paypal"

    def __init__(
        self,
        client_id,
        secret,
        endpoint="https://api.sandbox.paypal.com",
        webhook_id="",
        capture=True,
    ):
        self.secret = secret
        self.client_id = client_id
        self.endpoint = endpoint
        self.webhook_id = webhook_id
        self.oauth2_url = self.endpoint + "/v1/oauth2/token"
        self.order_url = self.endpoint + "/v2/checkout/orders"
        super().__init__(capture=capture)

    def get_cancel_info(self, subscription):
        if not subscription.remote_reference:
            return CancelInfo(
                False, _("You cannot cancel your Paypal subscription here.")
            )
        if subscription.canceled:
            return CancelInfo(
                False, _("Your Paypal subscription has already been canceled.")
            )
        return CancelInfo(True, _("You can cancel your Paypal subscription."))

    def get_modify_info(self, subscription):
        if not subscription.remote_reference:
            return ModifyInfo(
                False, _("You cannot modify your Paypal subscription here."), False
            )
        if not subscription.active:
            return ModifyInfo(
                False,
                _(
                    "You can modify your subscription when it receives the first payment."
                ),
                False,
            )
        if subscription.canceled:
            return ModifyInfo(
                False, _("Your Paypal subscription has already been canceled."), False
            )
        return ModifyInfo(True, _("You can modify your Paypal subscription."), False)

    def get_form(self, payment, data=None):
        """
        Converts *payment* into a form suitable for Django templates.
        """

        order = payment.order
        if not order.is_recurring:
            return self.setup_order(payment, data=data)
        return self.setup_subscription(payment, data=data)

    def setup_order(self, payment, data=None):
        if not payment.id:
            payment.save()
        links = self._get_links(payment)
        redirect_to = links.get("approve")
        if not redirect_to:
            approve_url = self.create_order(payment)
        else:
            approve_url = redirect_to["href"]
        payment.change_status_and_save(PaymentStatus.INPUT)
        raise RedirectNeeded(approve_url)

    def create_order(self, payment, extra_data=None):
        product_data = self.get_product_data(payment, extra_data)
        payment_data = self.post_api(self.order_url, product_data)
        self.set_response_data(payment, payment_data)
        links = self._get_links(payment)
        redirect_to = links["approve"]
        return redirect_to["href"]

    def get_transactions_data(self, payment):
        total = payment.total.quantize(CENTS, rounding=ROUND_HALF_UP)
        data = {
            "purchase_units": [
                {
                    "description": payment.description[:127] or "-",
                    "custom_id": str(payment.order.token),
                    "invoice_id": str(payment.order.token),
                    "amount": {
                        "value": str(total),
                        "currency_code": payment.currency.upper(),
                    },
                }
            ],
        }
        return data

    def get_product_data(self, payment, extra_data=None):
        return_url = self.get_return_url(payment)
        data = self.get_transactions_data(payment)
        data.update(
            {
                "intent": "CAPTURE",
                "processing_instruction": "ORDER_COMPLETE_ON_PAYMENT_APPROVAL",
                "application_context": {
                    "brand_name": settings.SITE_NAME,
                    "user_action": "PAY_NOW",
                    "return_url": return_url,
                    "cancel_url": return_url,
                },
            }
        )
        data["payer"] = {"payment_method": "paypal"}
        return data

    def process_data(self, payment, request):
        order = payment.order
        if not order.is_recurring:
            return self.process_order(payment, request)
        return self.finalize_subscription(payment)

    def set_response_data(self, payment, response):
        extra_data = json.loads(payment.extra_data or "{}")
        extra_data["response"] = response
        if "links" in response:
            extra_data["links"] = {link["rel"]: link for link in response["links"]}
        payment.extra_data = json.dumps(extra_data)
        payment.transaction_id = response["id"]
        payment.save(update_fields=["transaction_id", "extra_data"])

    def set_error_data(self, payment, error):
        extra_data = json.loads(payment.extra_data or "{}")
        extra_data["error"] = error
        payment.extra_data = json.dumps(extra_data)
        payment.save(update_fields=["extra_data"])

    def capture_payment(self, payment):
        links = self._get_links(payment)
        if "capture" not in links:
            raise ValueError("Could not capture")
        capture_url = links["capture"]["href"]
        response = self.post_api(capture_url, {})
        self.set_response_data(payment, response)
        return response

    def _get_links(self, payment):
        extra_data = json.loads(payment.extra_data or "{}")
        links = extra_data.get("links", {})
        return links

    def process_order(self, payment, request):
        success_url = payment.get_success_url()
        failure_url = payment.get_failure_url()
        if "token" not in request.GET:
            return HttpResponseForbidden("FAILED")
        payer_id = request.GET.get("PayerID")
        if not payer_id:
            if payment.status != PaymentStatus.CONFIRMED:
                payment.change_status_and_save(PaymentStatus.REJECTED)
                return redirect(failure_url)
            else:
                return redirect(success_url)
        try:
            captured_payment = self.capture_payment(payment)
        except PaymentError:
            return redirect(failure_url)

        if captured_payment is None:
            return redirect(success_url)
        if self._capture:
            payment.captured_amount = payment.total
            payment.change_status_and_save(PaymentStatus.CONFIRMED)
        else:
            payment.change_status_and_save(PaymentStatus.PREAUTH)
        return redirect(success_url)

    def _get_access_token(self):
        headers = {"Accept": "application/json", "Accept-Language": "en_US"}
        post = {"grant_type": "client_credentials"}
        response = requests.post(
            self.oauth2_url,
            data=post,
            headers=headers,
            auth=(self.client_id, self.secret),
            verify=not settings.DEBUG,
        )
        response.raise_for_status()
        data = response.json()
        return "%s %s" % (data["token_type"], data["access_token"])

    def get_api(self, url, params):
        access_token = self._get_access_token()
        headers = {"Content-Type": "application/json", "Authorization": access_token}
        response = requests.get(
            url, params=params, headers=headers, verify=not settings.DEBUG
        )
        return response.json()

    def post_api(self, url, request_data, method="POST"):
        access_token = self._get_access_token()
        headers = {
            "Content-Type": "application/json",
            "Authorization": access_token,
            "Prefer": "return=representation",
        }
        response = requests.request(
            method, url, json=request_data, headers=headers, verify=not settings.DEBUG
        )
        try:
            data = response.json()
        except ValueError:
            data = {}
        if 400 <= response.status_code <= 500:
            logger.debug(data)
            message = "Paypal error on {}".format(url)
            if response.status_code == 400:
                error_data = response.json()
                logger.warning(
                    message,
                    extra={"response": error_data, "status_code": response.status_code},
                )
                message = error_data.get("message", message)
            else:
                logger.warning(message, extra={"status_code": response.status_code})
            raise ValueError(message)
        return data

    def handle_webhook(self, request):
        if "PAYPAL-TRANSMISSION-ID" not in request.headers:
            return HttpResponse(status=400)

        try:
            data = json.loads(request.body.decode("utf-8"))
        except ValueError:
            return HttpResponse(status=400)

        if not self.verify_webhook(request, data) and not settings.DEBUG:
            return HttpResponse(status=400)
        logger.info("Paypal webhook: %s", data)
        method_name = data["event_type"].replace(".", "_").lower()
        method = getattr(self, "webhook_%s" % method_name, None)
        if method is None:
            return HttpResponse(status=204)

        method(request, data)

        return HttpResponse(status=204)

    def webhook_billing_subscription_activated(self, request, data):
        resource = data["resource"]
        sub_remote_reference = resource["id"]
        try:
            subscription = Subscription.objects.get(
                remote_reference=sub_remote_reference
            )
        except Subscription.DoesNotExist:
            return
        old_sub_status = subscription.active
        subscription.active = True
        subscription.save()
        if old_sub_status != subscription.active:
            subscription_activated.send(sender=subscription)

        logger.info("Paypal webhook subscription activated %s", subscription.id)

    def webhook_billing_subscription_cancelled(self, request, data):
        resource = data["resource"]
        sub_remote_reference = resource["id"]
        try:
            subscription = Subscription.objects.get(
                remote_reference=sub_remote_reference
            )
        except Subscription.DoesNotExist:
            return
        old_sub_status = subscription.active
        subscription.active = False
        if not subscription.canceled:
            subscription.canceled = timezone.now()
        if not subscription.cancel_trigger:
            subscription.cancel_trigger = "webhook"
        subscription.save()
        if old_sub_status != subscription.active:
            subscription_canceled.send(sender=subscription)

        logger.info("Paypal webhook subscription canceled %s", subscription.id)

    def extract_amounts(self, resource) -> TransactionAmounts:
        if "seller_receivable_breakdown" in resource:
            breakdown = resource["seller_receivable_breakdown"]
            total = breakdown["gross_amount"]["value"]
            fee = breakdown["paypal_fee"]["value"]
        elif "amount" in resource:
            amount = resource["amount"]
            if "total" in amount:
                total = amount["total"]
            elif "value" in amount:
                total = amount["value"]
            else:
                raise ValueError("Could not extract total amount")
            fee = resource["transaction_fee"]["value"]
        elif "amount_with_breakdown" in resource:
            total = resource["amount_with_breakdown"]["gross_amount"]["value"]
            fee = resource["amount_with_breakdown"]["fee_amount"]["value"]
        else:
            raise ValueError("Could not extract amounts")

        return TransactionAmounts(amount=Decimal(total), fee=Decimal(fee))

    def webhook_payment_capture_completed(self, request, data):
        resource = data["resource"]
        invoice_id = resource["invoice_id"]
        try:
            payment = Payment.objects.get(order__token=invoice_id)
        except Payment.DoesNotExist:
            return
        logger.info("Paypal webhook capture completed for payment %s", payment.id)
        payment.attrs.paypal_resource = resource
        amounts = self.extract_amounts(resource)
        payment.captured_amount = amounts.amount
        payment.received_amount = amounts.amount - amounts.fee
        payment.received_timestamp = dateutil.parser.parse(resource["create_time"])
        payment.change_status_and_save(PaymentStatus.CONFIRMED)

    def webhook_payment_sale_completed(self, request, data):
        resource = data["resource"]
        if "parent_payment" in resource:
            payment_reference = resource["parent_payment"]
            try:
                payment = Payment.objects.get(transaction_id=payment_reference)
            except Payment.DoesNotExist:
                return
        elif "billing_agreement_id" in resource:
            sub_reference = resource["billing_agreement_id"]
            try:
                subscription = Subscription.objects.get(
                    remote_reference=sub_reference, plan__provider=self.provider_name
                )
            except Subscription.DoesNotExist:
                return
            old_sub_status = subscription.active
            subscription.active = True
            subscription.save()

            if old_sub_status != subscription.active:
                if subscription.active:
                    subscription_activated.send(sender=subscription)
                else:
                    subscription_deactivated.send(sender=subscription)

            order = subscription.get_last_order()
            soon = timezone.now() + timedelta(days=2)
            if order.service_end < soon:
                payment = subscription.create_recurring_order(force=True)
            else:
                payment = Payment.objects.get(order=order)
        else:
            return

        logger.info("Paypal webhook sale complete for payment %s", payment.id)
        payment.attrs.paypal_resource = resource

        amounts = self.extract_amounts(resource)
        payment.captured_amount = amounts.amount
        payment.received_amount = amounts.amount - amounts.fee

        payment.received_timestamp = dateutil.parser.parse(resource["create_time"])
        payment.change_status_and_save(PaymentStatus.CONFIRMED)

    def verify_webhook(self, request, data):
        def get_header(key):
            return request.headers.get(key, "")

        verify_data = {
            "transmission_id": get_header("PAYPAL-TRANSMISSION-ID"),
            "transmission_time": get_header("PAYPAL-TRANSMISSION-TIME"),
            "cert_url": get_header("PAYPAL-CERT-URL"),
            "auth_algo": get_header("PAYPAL-AUTH-ALGO"),
            "transmission_sig": get_header("PAYPAL-TRANSMISSION-SIG"),
            "webhook_id": self.webhook_id,
            "webhook_event": data,
        }
        verify_url = self.endpoint + ("/v1/notifications/verify-webhook-signature")
        response = self.post_api(verify_url, verify_data)
        return response["verification_status"] == "SUCCESS"

    def finalize_subscription(self, payment):
        order = payment.order

        if not order.is_fully_paid():
            self.capture_subscription_order(order, payment=payment)
        return redirect(payment.get_success_url())

    def update_payment(self, payment):
        data = json.loads(payment.extra_data or "{}")
        if data.get("response"):
            resource = data["response"]["transactions"][0]
            resource = resource["related_resources"][0]["sale"]
        elif "paypal_resource" not in data:
            return
        else:
            resource = data["paypal_resource"]
        create_time = dateutil.parser.parse(resource["create_time"])
        if not resource.get("amount") and not resource.get("response"):
            buffer = timedelta(days=2)
            start = create_time - buffer
            end = create_time + buffer
            url = self.endpoint + (
                "/v1/billing/subscriptions/{id}/transactions?"
                "start_time={start}&end_time={end}"
            ).format(
                id=resource["id"], start=utcisoformat(start), end=utcisoformat(end)
            )
            result = self.get_api(url, {})
            transactions = [
                t
                for t in result["transactions"]
                if (
                    dateutil.parser.parse(t["time"]) - buffer < create_time
                    and dateutil.parser.parse(t["time"]) + buffer > create_time
                )
            ]
            assert len(transactions) == 1
            transaction = transactions[0]
            payment.transaction_id = transaction["id"]
            amounts = self.extract_amounts(transaction)
            payment.captured_amount = amounts.amount
            payment.received_amount = payment.captured_amount - amounts.fee
            payment.received_timestamp = create_time
            success = transaction["status"] == "COMPLETED"
        else:
            amounts = self.extract_amounts(resource)
            payment.captured_amount = amounts.amount
            payment.received_amount = payment.captured_amount - amounts.fee
            payment.received_timestamp = create_time
            success = resource["state"] == "completed"
        if success:
            payment.change_status_and_save(PaymentStatus.CONFIRMED)
        payment.save()

    def synchronize_orders(self, subscription):
        list_url = "{e}/v1/billing/subscriptions/{s}/transactions".format(
            e=self.endpoint, s=subscription.remote_reference
        )
        params = {
            "start_time": utcisoformat(subscription.last_date),
            "end_time": utcisoformat(subscription.last_date),
        }
        self.get_api(list_url, params)

    def cancel_subscription(self, subscription):
        cancel_url = "{e}/v1/billing/subscriptions/{sub_id}/cancel".format(
            e=self.endpoint, sub_id=subscription.remote_reference
        )
        cancel_data = {"reason": "unknown"}
        logger.info("Paypal subscription cancel %s", subscription.id)
        try:
            self.post_api(cancel_url, cancel_data)
        except ValueError as e:
            # canceling failed
            logger.info("Paypal subscription cancel failed %s", subscription.id)
            logger.exception(e)
            return False

        return True

    def modify_subscription(self, subscription, amount, interval):
        modify_url = "{e}/v1/billing/subscriptions/{sub_id}/revise".format(
            e=self.endpoint, sub_id=subscription.remote_reference
        )
        current_plan = subscription.plan
        new_plan = self.get_or_create_plan(
            current_plan.name,
            current_plan.category,
            amount,
            interval,
        )
        modify_data = {"plan_id": new_plan.remote_reference}
        try:
            self.post_api(modify_url, modify_data)
        except ValueError as e:
            # modification failed
            logger.info("Paypal subscription modification failed %s", subscription.id)
            logger.exception(e)
            return False

        subscription.plan = new_plan
        subscription.save()
        return True

    def capture_subscription_order(self, order, payment=None):
        subscription = order.subscription
        if payment is None:
            payment = order.get_or_create_payment(self.provider_name)
        capture_url = "{e}/v1/billing/subscriptions/{sub_id}/capture".format(
            e=self.endpoint, sub_id=subscription.remote_reference
        )
        capture_data = {
            "note": subscription.plan.name,
            "capture_type": "OUTSTANDING_BALANCE",
            "amount": {
                "currency_code": order.currency,
                "value": str(order.total_gross),
            },
        }
        try:
            response = self.post_api(capture_url, capture_data)
        except ValueError:
            # can't capture
            return
        if response["status"] in ("COMPLETED", "PARTIALLY_REFUNDED"):
            payment.transaction_id = response["id"]
            amounts = self.extract_amounts(response)
            payment.captured_amount = amounts.amount
            payment.received_amount = payment.captured_amount - amounts.fee
            payment.change_status_and_save(PaymentStatus.CONFIRMED)
        elif response["status"] == "PENDING":
            payment.change_status_and_save(PaymentStatus.PENDING)
        elif response["status"] == "REFUNDED":
            payment.change_status_and_save(PaymentStatus.REFUNDED)
        else:
            payment.change_status_and_save(PaymentStatus.REJECTED)

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
                        "surname": customer.last_name,
                    },
                    "email_address": customer.user_email,
                },
                "application_context": {
                    "brand_name": settings.SITE_NAME,
                    "locale": settings.LANGUAGE_CODE,
                    "shipping_preference": "NO_SHIPPING",
                    "user_action": "SUBSCRIBE_NOW",
                    "payment_method": {
                        "payer_selected": "PAYPAL",
                        "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED",
                    },
                    "return_url": return_url,
                    "cancel_url": return_url,
                },
            }
            subscription_url = self.endpoint + "/v1/billing/subscriptions"
            data = self.post_api(subscription_url, subscription_data)
            subscription.remote_reference = data["id"]
            subscription.save()
            approve_urls = [
                link["href"] for link in data["links"] if link["rel"] == "approve"
            ]
            if approve_urls:
                raise RedirectNeeded(approve_urls[0])

    def get_or_create_product(self, category):
        try:
            product = Product.objects.get(
                category=category, provider=self.provider_name
            )
        except Product.DoesNotExist:
            home_url = settings.SITE_URL
            if "localhost" in home_url:
                home_url = "http://example.org"
            product_data = {
                "name": category,
                "type": "SERVICE",
                "home_url": home_url,
            }
            product_url = self.endpoint + "/v1/catalogs/products"
            data = self.post_api(product_url, product_data)

            product = Product.objects.create(
                name="{provider} {category}".format(
                    provider=self.provider_name, category=category
                ),
                category=category,
                provider=self.provider_name,
                remote_reference=data["id"],
            )
        return product

    def get_or_create_plan(self, plan_name, category, amount, month_interval):
        product = self.get_or_create_product(category)
        try:
            plan = Plan.objects.get(
                product=product,
                amount=amount,
                interval=month_interval,
                provider=self.provider_name,
            )
        except Plan.DoesNotExist:
            plan_data = {
                "product_id": product.remote_reference,
                "name": plan_name,
                "description": plan_name,
                "billing_cycles": [
                    {
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
                                "currency_code": settings.DEFAULT_CURRENCY,
                            }
                        },
                    }
                ],
                "payment_preferences": {
                    "auto_bill_outstanding": True,
                    "setup_fee_failure_action": "CONTINUE",
                    "payment_failure_threshold": 0,
                },
            }
            plan_url = self.endpoint + "/v1/billing/plans"
            data = self.post_api(plan_url, plan_data)

            plan = Plan.objects.create(
                name=plan_name,
                slug=slugify(plan_name),
                category=category,
                amount=amount,
                interval=month_interval,
                amount_year=amount * Decimal(12 / month_interval),
                provider=self.provider_name,
                remote_reference=data["id"],
                product=product,
            )
        return plan
