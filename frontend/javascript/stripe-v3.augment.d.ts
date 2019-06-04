declare namespace stripe {
  interface PaymentIntent {
    status: string
  }
  interface PaymentIntentResponse {
    paymentIntent?: PaymentIntent;
    error?: Error;
  }
  interface PaymentIntentOptions {
    payment_method: string
  }
  interface PaymentRequestResult {
    error?: Error;
  }
  interface Stripe {
    handleCardPayment(clientSecret: string, element?: stripe.elements.Element): Promise<PaymentIntentResponse>
    confirmPaymentIntent(clientSecret: string, options: PaymentIntentOptions): Promise<PaymentRequestResult>
  }
  namespace paymentRequest {
    interface StripeRequestPaymentResponse {
      paymentMethod: {id: string}
      complete(status: string): void
    }
    interface StripePaymentRequest {
      on(event: 'paymentmethod', handler: (response: StripeRequestPaymentResponse) => void): void;
    }
  }
}
