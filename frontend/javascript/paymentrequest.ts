import { ConfirmCardPaymentData, PaymentRequestPaymentMethodEvent } from "@stripe/stripe-js"
import { BasePaymentMethod } from "./base"


export default class PaymentRequestButton extends BasePaymentMethod {

  async setup(prContainer: HTMLElement): Promise<boolean> {
    if (!this.payment.stripe || !this.payment.elements) {
      console.error('Stripe not initialized')
      return false
    }

    const paymentRequest = this.payment.stripe.paymentRequest({
      country: this.payment.config.stripecountry,
      currency: this.payment.config.currency,
      total: {
        label: this.payment.config.label,
        amount: this.payment.config.amount
      },
      requestPayerName: false,
      requestPayerEmail: false,
    })

    const prButton = this.payment.elements.create('paymentRequestButton', {
      paymentRequest: paymentRequest,
      style: {
        paymentRequestButton: {
          type: this.payment.config.donation ? 'donate' : 'default', //  | 'donate' | 'buy', // default: 'default'
          theme: 'dark',
          height: '64px' // default: '40px', the width is always '100%'
        }
      }
    })

    // Check the availability of the Payment Request API first.
    const result = await paymentRequest.canMakePayment()
    if (result) {
      prContainer.hidden = false
      paymentRequest.on('paymentmethod', this.onPaymentMethod.bind(this))

      prButton.mount('#payment-request-button')
      return true
    }
    return false
  }

  async onPaymentMethod(ev: PaymentRequestPaymentMethodEvent) {
    if (!this.payment.stripe || !this.payment.config.clientSecret) {
      console.error('Stripe not initialized')
      return
    }

    this.payment.ui.setPending(true)

    if (this.payment.config.interval > 0) {
      const response = await this.payment.sendPaymentData({
        payment_method_id: ev.paymentMethod.id
      })

      if (response.error) {
        ev.complete('fail')
        console.error("paymentRequest failed sending paymentMethod", response.error)
        this.payment.ui.showError(response.error)
        return
        // Show error from server on payment form
      } else if (response.requires_action) {
        // Use Stripe.js to handle required card action
        const actionResult = await this.payment.stripe.confirmCardPayment(response.payment_intent_client_secret)
        if (actionResult.error) {
          ev.complete('fail')
          console.error("paymentRequest failed confirmCardPayment recurring", actionResult.error)
          this.payment.ui.showError(actionResult.error.message)
          return
        }
      }
      ev.complete('success')
      this.payment.onSuccess()
      return
    }

    const data = {
      payment_method: ev.paymentMethod.id,
    } as ConfirmCardPaymentData

    const confirmResult = await this.payment.stripe.confirmCardPayment(this.payment.config.clientSecret, data)
    if (confirmResult.error) {
      // Report to the browser that the payment failed, prompting it to
      // re-show the payment interface, or show an error message and close
      // the payment interface.
      ev.complete('fail')
      console.error("paymentRequest failed confirmCardPayment", confirmResult.error)
      this.payment.ui.showError(confirmResult.error.message)
    } else {
      // Report to the browser that the confirmation was successful, prompting
      // it to close the browser payment method collection interface.
      ev.complete('success')

      if (confirmResult.paymentIntent && confirmResult.paymentIntent.status === "requires_action") {
        // Let Stripe.js handle the rest of the payment flow.
        const actionResult = await this.payment.stripe.confirmCardPayment(this.payment.config.clientSecret)
        if (actionResult.error) {
          console.error("paymentRequest failed confirmCardPayment 2", actionResult.error)
          this.payment.ui.showError(actionResult.error.message)
          return
        }
      }
      this.payment.onSuccess()
    }
  }
}
