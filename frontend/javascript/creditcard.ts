import { StripeCardElement } from '@stripe/stripe-js';
import { BasePaymentMethod } from './base';
import { PaymentProcessingResponse } from './types';

const stripeCardStyle = {
  base: {
    color: '#32325d',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    fontSmoothing: 'antialiased',
    fontSize: '16px',
    '::placeholder': {
      color: '#aab7c4'
    },
    ':-webkit-autofill': {
      color: '#32325d'
    }
  },
  invalid: {
    color: '#fa755a',
    iconColor: '#fa755a',
    ':-webkit-autofill': {
      color: '#fa755a'
    }
  }
};

export default class CreditCard extends BasePaymentMethod {
  card: StripeCardElement | null = null

  async setup(cardElement: HTMLElement) {
    if (!this.payment.elements) {
      console.error('Stripe Elements not initialized')
      return null
    }
    // Create an instance of the card Element.
    this.card = this.payment.elements.create('card', {
      style: stripeCardStyle
    })

    // Add an instance of the card Element into the `card-element` <div>.
    this.card.mount(cardElement)
    this.card.on('change', (event) => {
      const displayError = document.getElementById('card-errors')
      if (!displayError) {
        return
      }
      if (event && event.error) {
        displayError.textContent = event.error.message || 'Card Error'
      } else {
        displayError.textContent = ''
      }
    })
  }

  async handleCardPayment(card: StripeCardElement) {
    if (!this.payment.stripe || !this.payment.config.clientSecret) {
      console.error('Stripe not initialized')
      return
    }
    if (!card) { return }
    const result = await this.payment.stripe.confirmCardPayment(this.payment.config.clientSecret, {
      payment_method: {
        card,
      }
    })
    if (result.error) {
      console.error("confirmCardPayment failed", result.error)
      this.payment.ui.showError(result.error.message)
    } else if (result.paymentIntent && result.paymentIntent.status === 'succeeded') {
      this.payment.onSuccess()
    } else {
      console.error('Missing token!')
    }
  }

  async submit(event: Event) {
    if (!this.card) {
      console.error('Card element not initialized')
      return
    }
    event.preventDefault()
    if (!this.payment.config.clientSecret) { return }
    if (!this.payment.stripe) {
      console.error('Stripe not initialized')
      return
    }

    this.payment.ui.setPending(true)

    if (this.payment.config.interval === 0) {
      /* We have a payment intent */
      this.handleCardPayment(this.card)
    } else {
      const billing_details = {
        name: this.payment.config.name
      }
      const result = await this.payment.stripe.createPaymentMethod({
        type: 'card',
        card: this.card,
        billing_details
      })
      if (result.error) {
        console.error("createPaymentMethod for cc failed", result.error.message)
        this.payment.ui.showError(result.error.message)
      } else if (result.paymentMethod) {
        // Otherwise send paymentMethod.id to your server (see Step 2)
        const response = await this.payment.sendPaymentData({
          payment_method_id: result.paymentMethod.id
        })
        this.handleCreditCardServerResponse(response, this.card)
      }
    }
  }

  handleCreditCardServerResponse = (response: PaymentProcessingResponse, card: StripeCardElement) => {
    if (response.error) {
      console.error("handleServerResponse failed", response.error)
      this.payment.ui.showError(response.error)
      // Show error from server on payment form
    } else if (response.requires_action) {
      // Use Stripe.js to handle required card action
      this.payment.config.clientSecret = response.payment_intent_client_secret
      this.handleCardPayment(card)
    } else if (response.success) {
      this.payment.onSuccess()
    }
  }
}
