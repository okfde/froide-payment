interface PaymentProcessingResponse {
  error?: string
  type: string
  requires_action?: boolean
  payment_intent_client_secret: string
  payment_method?: string
  success?: boolean
  customer?: string
}

type SuccessMessage = {
  success: boolean
}

type PaymentMethodMessage = {
  payment_method_id: string
}

type SepaMessage = {
  iban: string
  owner_name: string
}

type PaymentMessage = SuccessMessage | PaymentMethodMessage | SepaMessage

const style = {
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
}

const paymentForm = document.getElementById('payment-form') as HTMLFormElement
const formButton = document.getElementById('form-button') as HTMLButtonElement
const currency = (paymentForm.dataset.currency || 'EUR').toLowerCase()

if (!paymentForm.dataset.stripepk) {
  throw new Error('No Stripe Public Key')
}

const clientSecret = paymentForm.dataset.clientsecret
let stripeOptions
if (clientSecret) {
  stripeOptions = {
    betas: ['payment_intent_beta_3']
  }
}
const stripe = Stripe(paymentForm.dataset.stripepk, stripeOptions)

const elements = stripe.elements({
  locale: paymentForm.dataset.locale
})

const sendPaymentData = (obj: PaymentMessage): Promise<PaymentProcessingResponse> => {
  return fetch(paymentForm.action, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest'
    },
    body: JSON.stringify(obj)
  }).then((response) => {
    return response.json()
  })
}

const handleCardPayment = async (clientSecret: string, card: stripe.elements.Element) => {
  if (!card) { return }
  const result = await stripe.confirmCardPayment(clientSecret, {
      payment_method: {
        card,
      }
  })
  if (result.error) {
    console.error("confirmCardPayment failed", result.error)
    showError(result.error.message)
  } else if (result.paymentIntent && result.paymentIntent.status === 'succeeded') {
    window.location.href = paymentForm.dataset.successurl || '/'
  } else {
    console.error('Missing token!')
  }
}

const handleServerResponse = (response: PaymentProcessingResponse, card: stripe.elements.Element) => {
  if (response.error) {
    console.error("handleServerResponse failed", response.error)
    showError(response.error)
    // Show error from server on payment form
  } else if (response.requires_action) {
    // Use Stripe.js to handle required card action
    handleCardPayment(response.payment_intent_client_secret, card)
  } else if (response.success) {
    document.location.href = paymentForm.dataset.successurl || '/'
  }
}

/*
 *
 *  Payment Intent with CC
 *
 */

const cardElement = document.querySelector('#card-element')

if (cardElement) {
  // Create an instance of the card Element.
  const card = elements.create('card', {
    style: style
  })

  // Add an instance of the card Element into the `card-element` <div>.
  card.mount('#card-element')
  card.on('change', (event) => {
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

  paymentForm.addEventListener('submit', async (event) => {
    event.preventDefault()
    if (!clientSecret) { return }

    setPending(true)

    if (!paymentForm.dataset.recurring) {
      /* We have a payment intent */
      handleCardPayment(clientSecret, card)
    } else {
      const billingDetails = {
        billing_details: {
          name: paymentForm.dataset.name
        }
      }
      const result = await stripe.createPaymentMethod('card', card, billingDetails)
      if (result.error) {
        console.error("createPaymentMethod for cc failed", result.error.message)
        showError(result.error.message)
      } else if (result.paymentMethod) {
        // Otherwise send paymentMethod.id to your server (see Step 2)
        const response = await sendPaymentData({
          payment_method_id: result.paymentMethod.id
        })
        handleServerResponse(response, card)
      }
    }
  })
}

/*
 *
 *  Stripe Sepa with custom IBAN handling
 *
 */

const iban = document.querySelector('input#id_iban') as HTMLInputElement
if (iban) {

  const additionalInfoFields = document.querySelector('#additional-sepa-info') as HTMLElement
  if (additionalInfoFields) {
    const toggleAdditionalInfo = () => {
      const ibanPattern = additionalInfoFields.dataset.ibanpattern
      if (!ibanPattern) { return }
      if (iban.value.match(`^${ibanPattern}.*$`)) {
        additionalInfoFields.removeAttribute("hidden")
        additionalInfoFields.querySelectorAll("input, select").forEach((el) => {
          el.setAttribute("required", "required")
        })
        additionalInfoFields.querySelectorAll("label").forEach((el) => {
          el.classList.add("field-required")
        })
        const countryCode = iban.value.substring(0, 2)
        const countrySelect = document.querySelector('select#id_country') as HTMLSelectElement
        if (countrySelect.querySelector(`option[value=${countryCode}]`)) {
          countrySelect.value = countryCode
        }
      } else {
        additionalInfoFields.setAttribute("hidden", "true")
        additionalInfoFields.querySelectorAll("input, select").forEach((el) => {
          el.removeAttribute("required")
        })
        additionalInfoFields.querySelectorAll("label").forEach((el) => {
          el.classList.remove("field-required")
        })
      }
    }

    iban.addEventListener("change", toggleAdditionalInfo)
    iban.addEventListener("keyup", toggleAdditionalInfo)
  }

  const getAdditionalSepaInfo = () => {
    if (!additionalInfoFields) { return {} }
    const fields = additionalInfoFields.querySelectorAll("input, select") as NodeListOf<HTMLInputElement | HTMLSelectElement>
    const data: {[key: string]: string} = {}
    fields.forEach((el) => {
      data[el.name] = el.value
    })
    return data
  }

  paymentForm.addEventListener('submit', async (event) => {
    event.preventDefault()
    const owner = document.querySelector('input#id_owner_name') as HTMLInputElement
    showLoading()
    try {
      const setupResponse = await sendPaymentData({
        iban: iban.value,
        owner_name: owner.value,
        ...getAdditionalSepaInfo()
      })
      if (setupResponse.error) {
        console.error("SEPA sendPaymentData failed", setupResponse.error)
        showError(setupResponse.error)
        return
      }

      let sepaData, confirmMethod
      if (setupResponse.type != "payment_intent") {
        sepaData = {
          payment_method: setupResponse.payment_method,
        } as stripe.ConfirmSepaDebitSetupData
        confirmMethod = stripe.confirmSepaDebitSetup
      } else {
        sepaData = {
          payment_method: setupResponse.payment_method,
          save_payment_method: setupResponse.customer
        } as stripe.ConfirmSepaDebitPaymentData
        confirmMethod = stripe.confirmSepaDebitPayment  
      }

      if (setupResponse.payment_intent_client_secret) {
        const confirmResponse = await confirmMethod(
          setupResponse.payment_intent_client_secret,
          sepaData
        )
        if (confirmResponse.error) {
          console.error("confirm sepa debit failed", setupResponse, confirmResponse.error)
          showError(confirmResponse.error.message)
          return
        }
      }
      await sendPaymentData({
        success: true
      })
      window.location.href = paymentForm.dataset.successurl || '/'
    } catch (e) {
      console.error(e)
      showError('Network failure.')
    }
  })
}

/*
 *
 *  Payment Request API
 *
 */

const prContainer = document.getElementById('payment-request') as HTMLElement

if (prContainer && clientSecret) {
  const paymentRequest = stripe.paymentRequest({
    country: paymentForm.dataset.country || 'DE',
    currency: currency,
    total: {
      label: paymentForm.dataset.label || '',
      amount: parseInt(paymentForm.dataset.amount || '0', 10)
    }
    // requestPayerName: true,
    // requestPayerEmail: true,
  })

  const prButton = elements.create('paymentRequestButton', {
    paymentRequest: paymentRequest,
    style: {
      paymentRequestButton: {
        type: paymentForm.dataset.donation ? 'donate' : 'default', //  | 'donate' | 'buy', // default: 'default'
        theme: 'dark',
        height: '64px' // default: '40px', the width is always '100%'
      }
    }
  })

  // Check the availability of the Payment Request API first.
  paymentRequest.canMakePayment().then((result) => {
    if (result) {
      prContainer.style.display = 'block'
      prButton.mount('#payment-request-button')
    }
  })

  paymentRequest.on('paymentmethod', async (ev) => {
    setPending(true)

    if (paymentForm.dataset.recurring) {
      const response = await sendPaymentData({
        payment_method_id: ev.paymentMethod.id
      })

      if (response.error) {
        ev.complete('fail')
        console.error("paymentRequest failed sending paymentMethod", response.error)
        showError(response.error)
        return
        // Show error from server on payment form
      } else if (response.requires_action) {
        // Use Stripe.js to handle required card action
        const actionResult = await stripe.confirmCardPayment(response.payment_intent_client_secret)
        if (actionResult.error) {
          ev.complete('fail')
          console.error("paymentRequest failed confirmCardPayment recurring", actionResult.error)
          showError(actionResult.error.message)
          return
        }
      }
      ev.complete('success')
      document.location.href = paymentForm.dataset.successurl || '/'
      return
    }

    const data = {
      payment_method: ev.paymentMethod.id,
      return_url: paymentForm.dataset.successurl,
    } as stripe.ConfirmCardPaymentData

    const confirmResult = await stripe.confirmCardPayment(clientSecret, data)
    if (confirmResult.error) {
      // Report to the browser that the payment failed, prompting it to
      // re-show the payment interface, or show an error message and close
      // the payment interface.
      ev.complete('fail')
      console.error("paymentRequest failed confirmCardPayment", confirmResult.error)
      showError(confirmResult.error.message)
    } else {
      // Report to the browser that the confirmation was successful, prompting
      // it to close the browser payment method collection interface.
      ev.complete('success')

      if (confirmResult.paymentIntent && confirmResult.paymentIntent.status === "requires_action") {
      // Let Stripe.js handle the rest of the payment flow.
        const actionResult = await stripe.confirmCardPayment(clientSecret)
        if (actionResult.error) {
          console.error("paymentRequest failed confirmCardPayment 2", actionResult.error)
          showError(actionResult.error.message)
          return
        }
      }
      window.location.href = paymentForm.dataset.successurl || '/'
    }
  })
}

/*
 *
 *  Helpers
 *
 */

const loading = document.getElementById('loading') as HTMLElement
const container = document.getElementById('container') as HTMLElement

const showError = (error: string | undefined) => {
  // Inform the customer that there was an error.
  const errorElement = document.getElementById('card-errors') as HTMLElement
  if (errorElement) {
    errorElement.style.display = 'block'
    errorElement.textContent = error || 'Card error'
  }
  setPending(false)
}

const setPending = (pending: boolean) => {
  if (formButton) {
    formButton.disabled = pending
  }
  if (pending) {
    showLoading()
  } else {
    stopLoading()
  }
}

function showLoading() {
  if (!loading) {
    throw new Error('No loading found')
  }
  if (!container) {
    throw new Error('No container found')
  }
  loading.style.display = 'block'
  container.style.display = 'none'
}
function stopLoading() {
  if (!loading) {
    throw new Error('No loading found')
  }
  if (!container) {
    throw new Error('No container found')
  }
  loading.style.display = 'none'
  container.style.display = 'block'
}
