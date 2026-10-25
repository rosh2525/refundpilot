import type { Payment } from './types';

type Balance = Pick<Payment, 'capture_id'|'status'|'amount_cents'|'refunded_cents'|'reserved_cents'>;
const capturedStates = new Set(['COMPLETED', 'PARTIALLY_REFUNDED', 'REFUNDED']);

export const capturedCents = (payment: Balance) =>
 payment.capture_id && capturedStates.has(payment.status) ? payment.amount_cents : 0;

export const availableCents = (payment: Balance) =>
 capturedCents(payment) ? Math.max(0, payment.amount_cents-payment.refunded_cents-payment.reserved_cents) : 0;
