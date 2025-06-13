import { StripeElementLocale } from '@stripe/stripe-js'
import { Payment } from './base'
import CreditCard from './creditcard'
import PaymentRequestButton from './paymentrequest'
import SepaDebit from './sepa'
import { DefaultUI } from './ui'

const setupPayment = async () => {

  const paymentForm = document.getElementById('payment-form') as HTMLFormElement

  const ui = new DefaultUI()
  const payment = new Payment(ui, {
    action: paymentForm.action,
    stripepk: paymentForm.dataset.stripepk || '',
    clientSecret: paymentForm.dataset.clientsecret || '',
    locale: <StripeElementLocale>document.documentElement.lang || "de",
    currency: (paymentForm.dataset.currency || 'EUR').toLowerCase(),
    amount: parseInt(paymentForm.dataset.amount || '0', 10),
    successurl: paymentForm.dataset.successurl || '',
    name: paymentForm.dataset.name || '',
    country: paymentForm.dataset.country || '',
    donation: paymentForm.dataset.donation === "1",
    recurring: paymentForm.dataset.recurring === "1",
    label: paymentForm.dataset.label || '',
    askInfo: false
  })
  await payment.init()

  const iban = document.querySelector('input#id_iban') as HTMLInputElement
  if (iban) {
    const method = new SepaDebit(payment)
    const ownerInput = document.querySelector('input#id_owner_name') as HTMLInputElement
    const additionalSepaInfoFields = document.querySelector('#additional-sepa-info') as HTMLElement
    method.setup(iban, ownerInput, additionalSepaInfoFields)
    paymentForm.addEventListener('submit', method.submit.bind(method))
  }

  const cardElement = document.getElementById('card-element') as HTMLElement
  if (cardElement) {
    const method = new CreditCard(payment)
    method.setup(cardElement)
    paymentForm.addEventListener('submit', method.submit.bind(method))

  }

  const prContainer = document.getElementById('payment-request') as HTMLElement
  if (prContainer) {
    const method = new PaymentRequestButton(payment)
    method.setup(prContainer)
  }

}

setupPayment()



// class QuickPaymentButtonMethod extends BasePaymentMethod {
//   elements: StripeElements | null = null

//   async setup() {
//     if (!this.payment.stripe || !this.payment.elements) {
//       console.error('Stripe Elements not initialized')
//       return
//     }

//     this.elements = this.payment.stripe.elements({
//       locale: this.payment.config.locale,
//       mode: 'payment',
//       amount: 1099,
//       currency: 'usd',

//     })

//     const expressCheckoutElement = this.payment.elements.create("expressCheckout", {
//       // emailRequired: true,
//       buttonHeight: 55,
//       buttonTheme: {
//         applePay: 'black'
//       },
//       buttonType: {
//         googlePay: 'book',
//         applePay: 'book',
//       },
//       // layout: 'auto',
//       // applePay: {
//       //   recurringPaymentRequest: {
//       //     paymentDescription: "Standard Subscription",
//       //     regularBilling: {
//       //       amount: 1000,
//       //       label: "Standard Package",
//       //       recurringPaymentStartDate: new Date("2023-03-31"),
//       //       recurringPaymentEndDate: new Date("2024-03-31"),
//       //       recurringPaymentIntervalUnit: "year",
//       //       recurringPaymentIntervalCount: 1,
//       //     },
//       //     billingAgreement: "billing agreement",
//       //     managementURL: "https://stripe.com",
//       //   }
//       // }
//     });
//     expressCheckoutElement.mount("#express-checkout-element");

//     const expressCheckoutDiv = document.getElementById('express-checkout-element');
//     expressCheckoutDiv.style.visibility = 'hidden';

//     expressCheckoutElement.on('ready', ({ availablePaymentMethods }) => {
//       if (!availablePaymentMethods) {
//         // No buttons will show
//       } else {
//         // Optional: Animate in the Element
//         expressCheckoutDiv.style.visibility = 'initial';
//       }
//     });



//     expressCheckoutElement.on('confirm', async (event) => {
//       const { error } = await stripe.confirmPayment({
//         // `Elements` instance that's used to create the Express Checkout Element.
//         elements,
//         // `clientSecret` from the created PaymentIntent
//         clientSecret,
//         confirmParams: {
//           return_url: 'https://example.com/order/123/complete',
//         },
//         // Uncomment below if you only want redirect for redirect-based payments.
//         // redirect: 'if_required',
//       });

//       if (error) {
//         // This point is reached only if there's an immediate error when confirming the payment. Show the error to your customer (for example, payment details incomplete).
//       } else {
//         // Your customer will be redirected to your `return_url`.
//       }
//     });

//   }
// }
