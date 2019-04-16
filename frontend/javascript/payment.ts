/// <reference path="./stripe-v3.augment.d.ts" />

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

const form = document.getElementById('payment-form') as HTMLFormElement
const currency = (form.dataset.currency || 'EUR').toLowerCase()

if (!form.dataset.stripepk) {
  throw new Error('No Stripe Public Key')
}

const clientSecret = form.dataset.clientsecret
let stripeOptions
if (clientSecret) {
  stripeOptions = {
    betas: ['payment_intent_beta_3']
  }
}
const stripe = Stripe(form.dataset.stripepk, stripeOptions)

const elements = stripe.elements({
  locale: form.dataset.locale
})

/*
 *
 *  Payment Intent with CC
 *
 */

const cardElement = document.querySelector('#card-element')

if (clientSecret && cardElement) {
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

  form.addEventListener('submit', (event) => {
    event.preventDefault()

    stripe.handleCardPayment(clientSecret, card).then((result) => {
      if (result.error) {
        // Inform the customer that there was an error.
        const errorElement = document.getElementById('card-errors')
        if (errorElement) {
          errorElement.textContent = result.error.message || 'Card error'
        }
      } else if (result.paymentIntent && result.paymentIntent.status === 'succeeded') {
        document.location.href = form.dataset.successurl || '/'
      } else {
        console.error('Missing token!')
      }
    })
  })

}

/*
 *
 *  SEPA
 *
 */

const ibanElement = document.querySelector('#iban-element')

if (ibanElement) {
  // Create an instance of the iban Element.
  const iban = elements.create('iban', {
    style: style,
    supportedCountries: ['SEPA'],
    placeholderCountry: form.dataset.country
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
        name: form.dataset.firstname + ' ' + form.dataset.lastname,
        email: form.dataset.email
        // address: {
        //   line1: form.dataset.address1,
        //   line2: form.dataset.address2,
        //   country: form.dataset.country,
        //   city: form.dataset.city,
        //   postal_code: form.dataset.postcode
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

function stripeSourceHandler (source: stripe.Source) {
  const hiddenInput = document.createElement('input')
  hiddenInput.setAttribute('type', 'hidden')
  hiddenInput.setAttribute('name', 'stripe_source')
  hiddenInput.setAttribute('value', source.id)
  form.appendChild(hiddenInput)

  // Submit the form.
  form.submit()
}

/*
 *
 *  Payment Request API
 *
 */

if (clientSecret) {
  const paymentRequest = stripe.paymentRequest({
    country: form.dataset.country || 'DE',
    currency: currency,
    total: {
      label: form.dataset.label || '',
      amount: parseInt(form.dataset.amount || '0', 10)
    }
    // requestPayerName: true,
    // requestPayerEmail: true,
  })

  const prButton = elements.create('paymentRequestButton', {
    paymentRequest: paymentRequest
  })

  // Check the availability of the Payment Request API first.
  paymentRequest.canMakePayment().then((result) => {
    if (result) {
      const prContainer = document.getElementById('payment-request')
      if (prContainer) {
        prContainer.style.display = 'block'
        prButton.mount('#payment-request-button')
      }
    }
  })

  paymentRequest.on('paymentmethod', (ev) => {
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
        stripe.handleCardPayment(clientSecret).then((result) => {
          if (result.error) {
            // The payment failed -- ask your customer for a new payment method.
          // Inform the customer that there was an error.
            const errorElement = document.getElementById('card-errors')
            if (errorElement) {
              errorElement.textContent = result.error.message || 'Card error'
            }
          } else if (result.paymentIntent && result.paymentIntent.status === 'succeeded') {
            document.location.href = form.dataset.successurl || '/'
          } else {
            console.error('Payment intent did not succeed.')
          }
        })
      }
    })
  })
}

/*
 *
 *  Helpers
 *
 */

const loading = document.getElementById('loading')
const container = document.getElementById('container')

function showLoading () {
  if (!loading) {
    throw new Error('No loading found')
  }
  if (!container) {
    throw new Error('No container found')
  }
  loading.style.display = 'block'
  container.style.display = 'none'
}
function stopLoading () {
  if (!loading) {
    throw new Error('No loading found')
  }
  if (!container) {
    throw new Error('No container found')
  }
  loading.style.display = 'none'
  container.style.display = 'block'
}
