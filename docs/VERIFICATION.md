# Observed deployment verification

Verified on 23 October 2026 against https://refundpilot.onrender.com.

## Passed

- Render Free Docker service in Singapore; Neon Free PostgreSQL in Singapore. No paid plan, card, or real bank was added.
- Hosted merchant login, authenticated workflow, and health endpoint.
- Database-backed preview request and simulated refund persisted across page reload.
- Separate official US sandbox Personal buyer with PayPal-generated fictional funding details.
- PayPal Orders v2: $20 buyer approval and completed capture.
- Capture data persisted through subsequent Render deployments.
- Gemini 3.5 Flash-Lite: actual API response, structured $5 refund recommendation, exact policy and customer quotations verified by server code.
- Explicit approval: $5 PayPal sandbox refund completed; original payment shows $5 refunded and $15 available.
- Actual signed PAYMENT.CAPTURE.COMPLETED notification accepted and recorded.
- $16 request against $15 remaining denied; no executable approval offered.
- 36 automated tests; GitHub CI passes tests, Alembic migration/check, frontend build, and dependency audit.
- Phone-width preview layout checked at 390px with no horizontal overflow.

## Still to complete before submission

- Confirm actual signed refund notification and resend deduplication with PayPal dashboard.
- Test pending-operation recovery during a controlled restart against deployed PostgreSQL; automated tests cover simulated recovery.
- Record broader model evaluation results using fixtures/evaluation_cases.json.
- Record and publish the English demo video under three minutes.
- Put dedicated judge login and buyer access into private submission testing instructions and retain access through judging.

These observations establish actual sandbox integration; no live funds were moved. Test transaction IDs and screenshots are kept in ignored local artifacts rather than published with credentials.
