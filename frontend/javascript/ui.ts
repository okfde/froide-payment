import { PaymentUI } from './types.ts'

export class DefaultUI implements PaymentUI {
  formButton: HTMLButtonElement
  loading: HTMLElement
  container: HTMLElement

  constructor() {
    this.formButton = document.getElementById('form-button') as HTMLButtonElement
    this.loading = document.getElementById('loading') as HTMLElement
    this.container = document.getElementById('container') as HTMLElement
  }
  showError(error: string | undefined) {
    // Inform the customer that there was an error.
    const errorElement = document.getElementById('card-errors') as HTMLElement
    if (errorElement) {
      errorElement.hidden = false
      errorElement.textContent = error || 'Card error'
    }
    this.setPending(false)
  }
  setPending(pending: boolean) {
    if (this.formButton) {
      this.formButton.disabled = pending
    }
    if (pending) {
      this.showLoading()
    } else {
      this.stopLoading()
    }
  }
  showLoading() {
    if (!this.loading) {
      throw new Error('No loading found')
    }
    if (!this.container) {
      throw new Error('No container found')
    }
    this.loading.hidden = false
    this.container.hidden = true
  }
  stopLoading() {
    if (!this.loading) {
      throw new Error('No loading found')
    }
    if (!this.container) {
      throw new Error('No container found')
    }
    this.loading.hidden = true
    this.container.hidden = false
  }
}
