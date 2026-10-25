# Testing

## Automated checks

```sh
pytest -q
alembic upgrade head
alembic check
npm --prefix frontend ci
npm --prefix frontend run test:csv
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=high
```

The current suite has 108 backend tests and 2 CSV security tests. Backend tests use isolated SQLite databases and controlled provider responses. They cover amount validation, authentication/CSRF, stale and modified proposals, concurrent reservations, idempotent retries, pending/failed/unknown outcomes, job recovery, webhook verification/deduplication, image normalization, evidence binding, and upload limits.

The Safety lab exercises the shared approval transaction in a separate temporary SQLite database. Its fixed blocked-recommendation scenario is not a Gemini prompt-injection benchmark. Lab results do not establish PayPal or PostgreSQL integration behavior.

## Hosted verification

Verified on 25 October 2026 against the Render/Neon sandbox deployment:

- Existing captured payments and completed refunds survived the schema migration.
- Earlier integration runs completed a $20 sandbox capture, merchant-approved $5 refunds, and signature-verified capture/refund notifications.
- A real Gemini request with a labeled synthetic illustration returned inconclusive visual observations. Approval was blocked and no refund operation was created for that case.
- The AG Grid workbench loaded payment records and exported CSV. Review-packet downloads preserved the evidence hash without including image bytes.
- All four hosted Safety lab scenarios passed. Local browser checks also covered filtering, sorting, zero-cost handling estimates, image upload, and phone-width form scrolling.

[CI for the verified runtime revision](https://github.com/rosh2525/refundpilot/actions/runs/40182664315)

These observations are integration examples, not a model-accuracy or production-readiness benchmark.

## Sandbox integration procedure

1. Configure providers and PostgreSQL using the [setup guide](SETUP.md). Sign in and confirm the application displays sandbox mode and a configured Gemini model.
2. Open **Payments → Create $20 sandbox purchase**. Approve the purchase using the separate sandbox buyer, return, and capture it. Confirm the provider status is `COMPLETED`.
3. Create a $5 request against that capture. Inspect the AI recommendation, exact quotations, and financial checks.
4. Confirm review and approve the exact proposal. Wait for a provider-confirmed `COMPLETED` refund and a $15 remaining balance. Retrying approval must not create a second operation.
5. Check a signed refund notification. Resend it from PayPal and verify it does not create duplicate financial operations.
6. Request more than the remaining balance; approval must be blocked. Test untrusted instructions separately and inspect the actual model result.
7. Attach fictional image evidence. Unclear or contradictory observations must block approval; changing an attachment must invalidate older proposals.
8. Test recovery during a controlled restart with a pending operation. Verify the persisted request ID is reused. Keep uncertain amounts reserved until provider reconciliation.

Record results without exposing credentials. PayPal simulator notifications are mock events and cannot establish that a payment occurred.

## Remaining integration coverage

Actual webhook resend/deduplication, a controlled pending-operation restart on deployed PostgreSQL, a completed image-backed refund, and a measured set of supporting/contradictory image examples remain to be verified. Automated coverage does not substitute for those checks.
