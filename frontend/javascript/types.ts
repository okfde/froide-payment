import { type StripeElementLocale } from '@stripe/stripe-js';

export interface PaymentUI {
    showError: (error: string | undefined) => void
    setPending: (pending: boolean) => void
    showLoading: () => void
    stopLoading: () => void
}

export type PaymentConfig = {
    action: string // URL to send payment data to
    stripepk: string
    clientSecret: string
    locale: StripeElementLocale
    country: string
    amount: number
    currency: string
    label: string
    successurl: string
    recurring: boolean
    name: string
    donation: boolean
    askInfo: boolean
}

export interface PaymentProcessingResponse {
    error?: string
    type: string
    requires_action?: boolean
    requires_confirmation?: boolean
    payment_intent_client_secret: string
    payment_method?: string
    success?: boolean
    customer?: boolean
}

export type SuccessMessage = {
    success: boolean
}

export type PaymentMethodMessage = {
    payment_method_id: string
}

export type SepaMessage = {
    iban: string
    owner_name: string
}

export type PaymentMessage = SuccessMessage | PaymentMethodMessage | SepaMessage
