import type { StripeElements, StripeElementsOptionsMode } from "@stripe/stripe-js";
import type { ApplePayUpdateOption } from "@stripe/stripe-js/dist/stripe-js/elements/apple-pay";
import { BasePaymentMethod } from "./base";
import type { AmountInterval, PartialPaymentConfig, PaymentProcessingResponse } from "./types";


export default class QuickPaymentButtonMethod extends BasePaymentMethod {
  elements: StripeElements | null = null

  async setup(expressCheckoutDiv: HTMLElement, basicConfig: PartialPaymentConfig): Promise<void> {
    if (!this.payment.stripe) {
      console.error('Stripe not initialized')
      return
    }
    const fallbackConfig: AmountInterval = { amount: 500, interval: 0 }
    let config: AmountInterval | null = null

    expressCheckoutDiv.addEventListener("donationchange", (event: CustomEvent<AmountInterval>) => {
      if (config === null) {
        // Optional: Animate in the Element
        expressCheckoutDiv.style.visibility = 'initial';
        const container = expressCheckoutDiv.closest(".quick-payment-container")
        container?.removeAttribute("hidden");
      }
      config = event.detail
    })

    function getElementsConfig(): StripeElementsOptionsMode {
      const localConfig: AmountInterval = config || fallbackConfig
      return {
        locale: basicConfig.locale,
        mode: localConfig.interval > 0 ? 'subscription' : 'payment',
        amount: localConfig.amount,
        currency: basicConfig.currency,
        captureMethod: 'automatic',
        setupFutureUsage: localConfig.interval > 0 ? 'off_session' : null,
      }
    }

    const getApplePayDetails = (): ApplePayUpdateOption | undefined => {
      const localConfig: AmountInterval = config || fallbackConfig
      return localConfig.interval > 0 ? {
        recurringPaymentRequest: {
          paymentDescription: basicConfig.label,
          regularBilling: {
            amount: localConfig.amount,
            label: basicConfig.label,
            recurringPaymentStartDate: undefined,
            recurringPaymentEndDate: undefined,
            recurringPaymentIntervalUnit: "month",
            recurringPaymentIntervalCount: localConfig.interval,
          },
          billingAgreement: basicConfig.label,
          managementURL: basicConfig.successurl,
        }
      } : { recurringPaymentRequest: undefined }
    }

    this.elements = this.payment.stripe.elements(getElementsConfig())
    const expressCheckoutElement = this.elements.create("expressCheckout", {
      emailRequired: true,
      business: {
        name: basicConfig.sitename,
      },
      billingAddressRequired: true,
      buttonHeight: 55,
      buttonTheme: {
        applePay: 'black'
      },
      buttonType: {
        googlePay: basicConfig.donation ? 'donate' : 'buy',
        applePay: basicConfig.donation ? 'donate' : 'buy',
      },
      applePay: getApplePayDetails()
    });

    expressCheckoutDiv.style.visibility = 'hidden';
    expressCheckoutElement.mount(expressCheckoutDiv);

    expressCheckoutElement.on('ready', ({ availablePaymentMethods }) => {
      if (!availablePaymentMethods) {
        // No buttons will show
      } else {
        expressCheckoutDiv.dispatchEvent(new CustomEvent("quickpaymentAvailable"));
      }
    });

    expressCheckoutElement.on("click", (event) => {
      if (!this.payment.stripe || !this.elements) {
        console.error('Stripe Elements not initialized')
        return
      }
      if (config === null) {
        console.error('No amount/interval config set')
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
          country: event.billingDetails.address?.country || basicConfig.country || 'DE',
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
            return_url: response.successurl || basicConfig.successurl,
          }
        });
        if (error) {
          // This point is reached only if there's an immediate error when confirming the payment. Show the error to your customer (for example, payment details incomplete).
          this.payment.ui.showError(error.message);
        } else {
          document.location.href = response.successurl || basicConfig.successurl || '/'
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
