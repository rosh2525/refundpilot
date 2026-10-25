import test from 'node:test';
import assert from 'node:assert/strict';
import { availableCents, capturedCents } from '../src/paymentBalance.ts';

const payment = {capture_id:'CAPTURE',status:'COMPLETED',amount_cents:2000,refunded_cents:500,reserved_cents:200};

test('uncaptured and pending payments never expose refundable funds', () => {
 for (const change of [{capture_id:null,status:'CREATED'},{capture_id:null,status:'APPROVED'},{status:'PENDING'},{status:'DENIED'},{status:'FAILED'}]) {
  const value={...payment,...change};
  assert.equal(capturedCents(value),0);
  assert.equal(availableCents(value),0);
 }
});

test('confirmed funds subtract completed refunds and unresolved reservations', () => {
 assert.equal(capturedCents(payment),2000);
 assert.equal(availableCents(payment),1300);
 assert.equal(availableCents({...payment,status:'PARTIALLY_REFUNDED'}),1300);
 assert.equal(availableCents({...payment,status:'REFUNDED',refunded_cents:2000,reserved_cents:0}),0);
});
