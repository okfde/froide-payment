import { StripeElementLocale } from '@stripe/stripe-js'
import { Payment } from './base'
import CreditCard from './creditcard'
import PaymentRequestButton from './paymentrequest'
import QuickPaymentButtonMethod from './quickpayment'
import SepaDebit from './sepa'
import { PaymentConfig } from './types'
import { DefaultUI, ErrorOnlyUI } from './ui'

const setupPayment = async (paymentForm: HTMLFormElement) => {

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
    stripecountry: paymentForm.dataset.stripecountry || '',
    donation: paymentForm.dataset.donation === "1",
    interval: parseInt(paymentForm.dataset.interval || '0', 10),
    label: paymentForm.dataset.label || '',
    sitename: paymentForm.dataset.sitename || '',
  })
  await payment.init()
  payment.setupElements()

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

const setupQuickPayment = async (container: HTMLElement, data: PaymentConfig) => {
  const ui = new ErrorOnlyUI(container)
  const payment = new Payment(ui, data)
  await payment.init()
  const method = new QuickPaymentButtonMethod(payment)
  method.setup(container, data)
}


const paymentForm = document.getElementById('payment-form') as HTMLFormElement
if (paymentForm) {
  setupPayment(paymentForm)
}


const quickPaymentContainers = document.querySelectorAll("[data-quickpayment]")
quickPaymentContainers.forEach((container) => {
  const quickPayment = container as HTMLElement
  const quickPaymentId = quickPayment.dataset.quickpayment
  const dataScript = document.getElementById(`${quickPaymentId}-data`)
  if (dataScript === null) {
    console.error(`No data script found for quick payment ${quickPaymentId}`);
    return;
  }
  const data = JSON.parse(dataScript.textContent || 'null');
  if (data === null) {
    console.error(`Invalid data for quick payment ${quickPaymentId}`);
    return;
  }
  setupQuickPayment(quickPayment, data)
})
