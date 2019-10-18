declare namespace stripe {
  interface PaymentIntent {
    id: string
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
  interface PaymentMethod {
    id: string;
  }
  interface PaymentMethodResponse {
    paymentMethod?: PaymentMethod;
    error?: Error;
  }
  interface PaymentMethodBillingDetails {
    name?: string;
    email?: string;
  }
  interface PaymentMethodDetails {
    billing_details: PaymentMethodBillingDetails;
  }

  interface Stripe {
    handleCardPayment(clientSecret: string, element?: stripe.elements.Element): Promise<PaymentIntentResponse>
    handleCardAction(clientSecret: string): Promise<PaymentIntentResponse>
    confirmPaymentIntent(clientSecret: string, options: PaymentIntentOptions): Promise<PaymentRequestResult>
    createPaymentMethod(type: string, element: stripe.elements.Element, data?: PaymentMethodDetails): Promise<PaymentMethodResponse>
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
