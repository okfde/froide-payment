import { type StripeElementLocale } from '@stripe/stripe-js';

export interface PaymentUI {
    showError: (error: string | undefined) => void
    setPending: (pending: boolean) => void
    showLoading: () => void
    stopLoading: () => void
}

export type PartialPaymentConfig = {
    action: string // URL to send payment data to
    stripepk: string
    clientSecret?: string
    locale: StripeElementLocale
    stripecountry: string
    country?: string
    currency: string
    label: string
    successurl: string
    name?: string
    donation: boolean
    sitename: string
}

export type PaymentConfig = PartialPaymentConfig & {
    amount: number // in cents
    interval: number
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
    successurl?: string
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

export type QuickPaymentMessage = {
    type: 'quickpayment'
    amount: number,
    currency: string,
    interval: number,
    name: string,
    email: string,
    city: string,
    postcode: string,
    country: string
    street_address_1: string
    street_address_2: string
}

export type PaymentMessage = SuccessMessage | PaymentMethodMessage | SepaMessage | QuickPaymentMessage

export interface AmountInterval {
    amount: number;
    interval: number; // for recurring payments
}

interface CustomEventMap {
    "donationchange": CustomEvent<AmountInterval>;
}
declare global {
    interface HTMLElement { //adds definition to Document, but you can do the same with HTMLElement
        addEventListener<K extends keyof CustomEventMap>(type: K,
            listener: (this: Document, ev: CustomEventMap[K]) => void): void;

    }
}
