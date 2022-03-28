interface PaymentProcessingResponse {
  error?: string
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

const handleCardPayment = (clientSecret: string, card?: stripe.elements.Element) => {
  if (!card) { return }
  stripe.handleCardPayment(clientSecret, card).then((result) => {
    if (result.error) {
      showError(result.error.message)
    } else if (result.paymentIntent && result.paymentIntent.status === 'succeeded') {
      window.location.href = paymentForm.dataset.successurl || '/'
    } else {
      console.error('Missing token!')
    }
  })
}

const handleServerResponse = (response: PaymentProcessingResponse) => {
  if (response.error) {
    showError(response.error)
    // Show error from server on payment form
  } else if (response.requires_action) {
    // Use Stripe.js to handle required card action
    handleCardPayment(response.payment_intent_client_secret)
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

  paymentForm.addEventListener('submit', (event) => {
    event.preventDefault()

    setPending(true)

    if (clientSecret) {
      /* We have a payment intent */
      handleCardPayment(clientSecret, card)
    } else {
      const billingDetails = {
        billing_details: {
          name: paymentForm.dataset.name
        }
      }
      stripe.createPaymentMethod('card', card, billingDetails).then((result) => {
        if (result.error) {
          showError(result.error.message)
        } else if (result.paymentMethod) {
          // Otherwise send paymentMethod.id to your server (see Step 2)
          sendPaymentData({
            payment_method_id: result.paymentMethod.id
          }).then((response) => {
            handleServerResponse(response)
          })
        }
      })
    }
  })
}

/*
 *
 *  Stripe Direct Sepa
 *  == Unused ==
 *
 */

const ibanElement = document.querySelector('#iban-element')

if (ibanElement) {
  // Create an instance of the iban Element.
  const iban = elements.create('iban', {
    style: style,
    supportedCountries: ['SEPA'],
    placeholderCountry: paymentForm.dataset.country
  })

  // Add an instance of the iban Element into the `iban-element` <div>.
  iban.mount('#iban-element')

  const errorMessage = document.getElementById('error-message')
  if (!errorMessage) {
    throw new Error('Missing error message field')
  }

  iban.on('change', (event) => {
    // Handle real-time validation errors from the iban Element.
    if (event && event.error) {
      errorMessage.textContent = event.error.message || 'IBAN error'
      errorMessage.classList.add('visible')
    } else {
      errorMessage.classList.remove('visible')
    }

    const bankName = document.getElementById('bank-name')
    if (bankName) {
      // Display bank name corresponding to IBAN, if available.
      if (event && event.bankName) {
        bankName.textContent = event.bankName
        bankName.classList.add('visible')
      } else {
        bankName.classList.remove('visible')
      }
    } else {
      console.error('Missing bank name field')
    }
  })

  const sepaSubmit = document.getElementById('sepa-submit')
  if (!sepaSubmit) {
    throw new Error('Missing sepa submit')
  }
  sepaSubmit.addEventListener('click', (event) => {
    event.preventDefault()
    showLoading()

    const sourceData = {
      type: 'sepa_debit',
      currency: currency,
      owner: {
        name: paymentForm.dataset.firstname + ' ' + paymentForm.dataset.lastname,
        email: paymentForm.dataset.email
        // address: {
        //   line1: paymentForm.dataset.address1,
        //   line2: paymentForm.dataset.address2,
        //   country: paymentForm.dataset.country,
        //   city: paymentForm.dataset.city,
        //   postal_code: paymentForm.dataset.postcode
        // }
      },
      mandate: {
        // Automatically send a mandate notification email to your customer
        // once the source is charged.
        notification_method: 'email'
      }
    }

    // Call `stripe.createSource` with the iban Element and additional options.
    stripe.createSource(iban, sourceData).then((result) => {
      if (result.error) {
        // Inform the customer that there was an error.
        errorMessage.textContent = result.error.message || 'source error'
        errorMessage.classList.add('visible')
        stopLoading()
      } else {
        // Send the Source to your server to create a charge.
        errorMessage.classList.remove('visible')
        if (result.source) {
          stripeSourceHandler(result.source)
        } else {
          console.error('No source given')
        }
      }
    })
  })
}

function stripeSourceHandler(source: stripe.Source) {
  const hiddenInput = document.createElement('input')
  hiddenInput.setAttribute('type', 'hidden')
  hiddenInput.setAttribute('name', 'stripe_source')
  hiddenInput.setAttribute('value', source.id)
  paymentForm.appendChild(hiddenInput)

  // Submit the paymentForm.
  paymentForm.submit()
}

/*
 *
 *  Stripe Sepa with custom IBAN handling
 *
 */

const iban = document.querySelector('input#id_iban') as HTMLInputElement
if (iban) {
  paymentForm.addEventListener('submit', (event) => {
    event.preventDefault()
    const owner = document.querySelector('input#id_owner_name') as HTMLInputElement
    showLoading()
    sendPaymentData({
      iban: iban.value,
      owner_name: owner.value
    }).then((response) => {
      if (response.error) {
        showError(response.error)
      } else {
        const sepaData = {
          payment_method: response.payment_method,
          save_payment_method: false
        } as any
        if (response.customer) {
          sepaData.setup_future_usage = 'off_session'
          sepaData.save_payment_method = true
        }
        stripe.confirmSepaDebitPayment(
          response.payment_intent_client_secret,
          sepaData
        ).then((response) => {
          if (response.error) {
            showError(response.error.message)
          } else {
            sendPaymentData({
              success: true
            }).then(() => {
              window.location.href = paymentForm.dataset.successurl || '/'
            }).catch(() => {
              showError('Network failure.')
            })
          }
        }).catch(() => {
          showError('Network failure.')
        })
      }
    }).catch(() => {
      showError('Network failure.')
    })
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

  paymentRequest.on('paymentmethod', (ev) => {

    if (clientSecret) {
      stripe.confirmPaymentIntent(clientSecret, {
        payment_method: ev.paymentMethod.id
      }).then((confirmResult) => {
        if (confirmResult.error) {
          // Report to the browser that the payment failed, prompting it to
          // re-show the payment interface, or show an error message and close
          // the payment interface.
          ev.complete('fail')
        } else {
          // Report to the browser that the confirmation was successful, prompting
          // it to close the browser payment method collection interface.
          ev.complete('success')
          // Let Stripe.js handle the rest of the payment flow.
          handleCardPayment(clientSecret)
        }
      })
    } else {
      /* No client secret, need to sent payment method */
      sendPaymentData({
        payment_method_id: ev.paymentMethod.id
      }).then((response) => {
        if (response.error) {
          ev.complete('fail')
        } else {
          ev.complete('success')
        }
        handleServerResponse(response)
      })
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
