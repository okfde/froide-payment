import { loadStripe, Stripe, StripeElements } from '@stripe/stripe-js';
import { PaymentConfig, PaymentMessage, PaymentProcessingResponse, PaymentUI } from './types';


export class Payment {
  config: PaymentConfig
  ui: PaymentUI
  stripePromise: Promise<Stripe | null>
  stripe: Stripe | null = null
  elements: StripeElements | null = null

  constructor(ui: PaymentUI, config: PaymentConfig) {
    this.ui = ui
    this.config = config
    if (!this.config.stripepk) {
      throw new Error('No Stripe Public Key')
    }
    this.stripePromise = loadStripe(this.config.stripepk);
  }

  async init() {
    this.ui.setPending(true)
    const stripe = await this.stripePromise
    if (!stripe) {
      console.error('Stripe not loaded')
      // maybe?
      document.location.reload()
      return
    }
    this.stripe = stripe

    this.elements = stripe.elements({
      locale: this.config.locale
    })

    this.ui.setPending(false)
  }

  async sendPaymentData(obj: PaymentMessage): Promise<PaymentProcessingResponse> {
    const response = await fetch(this.config.action, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(obj)
    })
    return await response.json()
  }

  onSuccess() {
    document.location.href = this.config.successurl || '/'
  }
}


export class BasePaymentMethod {
  protected payment: Payment

  constructor(payment: Payment) {
    this.payment = payment
  }
}

