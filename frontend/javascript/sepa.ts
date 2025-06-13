import { ConfirmSepaDebitPaymentData, ConfirmSepaDebitSetupData } from '@stripe/stripe-js';
import { BasePaymentMethod } from './base';

export default class SepaDebit extends BasePaymentMethod {
  iban: HTMLInputElement | null = null
  ownerInput: HTMLInputElement | null = null
  additionalInfoFields: HTMLElement | null = null

  setup(iban: HTMLInputElement, ownerInput: HTMLInputElement, additionalInfoFields: HTMLElement): void {
    this.iban = iban
    this.ownerInput = ownerInput
    this.additionalInfoFields = additionalInfoFields

    iban.addEventListener("change", this.toggleAdditionalInfo)
    iban.addEventListener("keyup", this.toggleAdditionalInfo)
  }

  toggleAdditionalInfo() {
    if (!this.iban || !this.additionalInfoFields) { return }
    const ibanPattern = this.additionalInfoFields.dataset.ibanpattern
    if (!ibanPattern) { return }
    if (this.iban.value.match(`^${ibanPattern}.*$`)) {
      this.additionalInfoFields.removeAttribute("hidden")
      this.additionalInfoFields.querySelectorAll("input, select").forEach((el) => {
        el.setAttribute("required", "required")
      })
      this.additionalInfoFields.querySelectorAll("label").forEach((el) => {
        el.classList.add("field-required")
      })
      const countryCode = this.iban.value.substring(0, 2)
      const countrySelect = document.querySelector('select#id_country') as HTMLSelectElement
      if (countrySelect.querySelector(`option[value=${countryCode}]`)) {
        countrySelect.value = countryCode
      }
    } else {
      this.additionalInfoFields.setAttribute("hidden", "true")
      this.additionalInfoFields.querySelectorAll("input, select").forEach((el) => {
        el.removeAttribute("required")
      })
      this.additionalInfoFields.querySelectorAll("label").forEach((el) => {
        el.classList.remove("field-required")
      })
    }
  }

  getAdditionalSepaInfo = () => {
    if (!this.additionalInfoFields) { return {} }
    const fields = this.additionalInfoFields.querySelectorAll("input, select") as NodeListOf<HTMLInputElement | HTMLSelectElement>
    const data: { [key: string]: string } = {}
    fields.forEach((el) => {
      data[el.name] = el.value
    })
    return data
  }

  async submit(event: Event) {
    event.preventDefault()
    if (!this.payment.stripe) {
      console.error('Stripe not initialized')
      return
    }
    if (!this.iban || !this.ownerInput) {
      console.error('SEPA fields not initialized')
      return
    }

    this.payment.ui.showLoading()
    try {
      const setupResponse = await this.payment.sendPaymentData({
        iban: this.iban.value,
        owner_name: this.ownerInput.value,
        ...this.getAdditionalSepaInfo()
      })
      if (setupResponse.error) {
        console.error("SEPA sendPaymentData failed", setupResponse.error)
        this.payment.ui.showError(setupResponse.error)
        return
      }

      let sepaData, confirmMethod
      if (setupResponse.type != "payment_intent") {
        sepaData = {
          payment_method: setupResponse.payment_method,
        } as ConfirmSepaDebitSetupData
        confirmMethod = this.payment.stripe.confirmSepaDebitSetup
      } else {
        sepaData = {
          payment_method: setupResponse.payment_method,
          save_payment_method: setupResponse.customer,
          setup_future_usage: 'off_session'
        } as ConfirmSepaDebitPaymentData
        confirmMethod = this.payment.stripe.confirmSepaDebitPayment
      }

      if (setupResponse.payment_intent_client_secret) {
        const confirmResponse = await confirmMethod(
          setupResponse.payment_intent_client_secret,
          sepaData
        )
        if (confirmResponse.error) {
          console.error("confirm sepa debit failed", setupResponse, confirmResponse.error)
          this.payment.ui.showError(confirmResponse.error.message)
          return
        }
      }
      await this.payment.sendPaymentData({
        success: true
      })
      this.payment.onSuccess()
    } catch (e) {
      console.error(e)
      this.payment.ui.showError('Network failure.')
    }
  }
}
