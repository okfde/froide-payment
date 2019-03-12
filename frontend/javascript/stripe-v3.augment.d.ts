declare namespace stripe {
  interface StripeOptions {
    betas: string[];
  }
  interface PaymentIntent {
    status: string
  }
  interface PaymentIntentResponse {
    paymentIntent?: PaymentIntent;
    error?: Error;
  }
  interface Stripe {
    handleCardPayment(clientSecret: string, element: stripe.elements.Element): Promise<PaymentIntentResponse>
  }
}
