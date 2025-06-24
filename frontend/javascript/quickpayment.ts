import type { StripeElements, StripeElementsOptionsMode } from "@stripe/stripe-js";
import type { ApplePayUpdateOption } from "@stripe/stripe-js/dist/stripe-js/elements/apple-pay";
import { BasePaymentMethod } from "./base";
import type { AmountInterval, PaymentConfig, PaymentProcessingResponse } from "./types";


export default class QuickPaymentButtonMethod extends BasePaymentMethod {
  elements: StripeElements | null = null

  async setup(expressCheckoutDiv: HTMLElement, config: PaymentConfig): Promise<void> {
    if (!this.payment.stripe) {
      console.error('Stripe not initialized')
      return
    }

    expressCheckoutDiv.addEventListener("donationchange", (event: CustomEvent<AmountInterval>) => {
      config = {
        ...config,
        ...event.detail
      }
    })

    function getElementsConfig(): StripeElementsOptionsMode {
      return {
        locale: config.locale,
        mode: config.interval > 0 ? 'subscription' : 'payment',
        amount: config.amount,
        currency: config.currency,
      }
    }

    const getApplePayDetails = (): ApplePayUpdateOption | undefined => {
      return config.interval > 0 ? {
        recurringPaymentRequest: {
          paymentDescription: config.label,
          regularBilling: {
            amount: config.amount,
            label: config.label,
            recurringPaymentStartDate: undefined,
            recurringPaymentEndDate: undefined,
            recurringPaymentIntervalUnit: "month",
            recurringPaymentIntervalCount: config.interval,
          },
          billingAgreement: config.label,
          managementURL: config.successurl,
        }
      } : { recurringPaymentRequest: undefined }
    }

    this.elements = this.payment.stripe.elements(getElementsConfig())
    const expressCheckoutElement = this.elements.create("expressCheckout", {
      emailRequired: true,
      business: {
        name: config.sitename,
      },
      billingAddressRequired: true,
      buttonHeight: 55,
      buttonTheme: {
        applePay: 'black'
      },
      buttonType: {
        googlePay: config.donation ? 'donate' : 'buy',
        applePay: config.donation ? 'donate' : 'buy',
      },
      applePay: getApplePayDetails()
    });

    expressCheckoutDiv.style.visibility = 'hidden';
    const container = expressCheckoutDiv.closest(".quick-payment-container")
    expressCheckoutElement.mount(expressCheckoutDiv);

    expressCheckoutElement.on('ready', ({ availablePaymentMethods }) => {
      if (!availablePaymentMethods) {
        // No buttons will show
      } else {
        // Optional: Animate in the Element
        expressCheckoutDiv.style.visibility = 'initial';
        container?.removeAttribute("hidden");
        expressCheckoutDiv.dispatchEvent(new CustomEvent("quickpaymentAvailable"));
      }
    });

    expressCheckoutElement.on("click", (event) => {
      if (!this.payment.stripe || !this.elements) {
        console.error('Stripe Elements not initialized')
        return
      }
      this.elements.update(getElementsConfig())
      event.resolve({
        applePay: getApplePayDetails()
      })
    });

    expressCheckoutElement.on('confirm', async (event) => {
      if (!this.payment.stripe || !this.elements) {
        console.error('Stripe Elements not initialized')
        return
      }
      if (!event.billingDetails) {
        event.paymentFailed({ "reason": "fail" })
        return
      }
      if (!event.billingDetails.email) {
        event.paymentFailed({ "reason": "fail" })
        return
      }
      this.payment.ui.showLoading();

      try {
        const response = await this.sendPayerData(expressCheckoutDiv, {
          name: event.billingDetails.name,
          email: event.billingDetails.email,
          city: event.billingDetails.address?.city || '',
          postcode: event.billingDetails.address?.postal_code || '',
          country: event.billingDetails.address?.country || config.country || 'DE',
          street_address_1: event.billingDetails.address?.line1 || '',
          street_address_2: event.billingDetails.address?.line2 || '',
        })
        if (response.error) {
          this.payment.ui.showError(response.error);
          return;
        }

        const { error } = await this.payment.stripe.confirmPayment({
          // `Elements` instance that's used to create the Express Checkout Element.
          elements: this.elements,
          // `clientSecret` from the created PaymentIntent
          clientSecret: response.payment_intent_client_secret,
          confirmParams: {
            return_url: response.successurl || config.successurl,
          },
          // Uncomment below if you only want redirect for redirect-based payments.
          // redirect: 'if_required',
        });
        if (error) {
          // This point is reached only if there's an immediate error when confirming the payment. Show the error to your customer (for example, payment details incomplete).
          this.payment.ui.showError(error.message);
        } else {
          document.location.href = response.successurl || config.successurl || '/'
        }
      } catch (err: unknown) {
        console.error('Error sending payment data:', err);
        if (err instanceof Error) {
          this.payment.ui.showError(err.message || 'An error occurred while processing the payment.');
        }
      }
    });
  }

  private async sendPayerData(expressCheckoutDiv: HTMLElement, data: any): Promise<PaymentProcessingResponse> {
    return new Promise((resolve, reject) => {
      const event = new CustomEvent("paymentConfirm", {
        detail: {
          resolve,
          reject,
          data,
        }
      })
      expressCheckoutDiv.dispatchEvent(event);
    })
  }
}
