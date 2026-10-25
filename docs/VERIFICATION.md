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
- Actual signed PAYMENT.CAPTURE.COMPLETED and PAYMENT.CAPTURE.REFUNDED notifications accepted and recorded.
- $16 request against $15 remaining denied; no executable approval offered.
- An instruction-injection request for $5 within the remaining balance produced needs_review and no executable approval.
- 36 automated tests; GitHub CI passes tests, Alembic migration/check, frontend build, and dependency audit.
- Phone-width preview layout checked at 390px with no horizontal overflow.

## Still to complete before submission

- Verify webhook resend deduplication using PayPal dashboard; initial signed capture and refund notifications already passed.
- Test pending-operation recovery during a controlled restart against deployed PostgreSQL; automated tests cover simulated recovery.
- Record broader model evaluation results using fixtures/evaluation_cases.json.
- Record and publish the English demo video under three minutes.
- Put dedicated judge login and buyer access into private submission testing instructions and retain access through judging.

These observations establish actual sandbox integration; no live funds were moved. Test transaction IDs and screenshots are kept in ignored local artifacts rather than published with credentials.


## 25 October 2026: bounded upgrade checks

- 108 backend tests pass, including image validation, evidence-bound approvals, upload limits, return estimates, and isolated approval simulations.
- Two CSV security tests pass; production frontend builds and the full dependency audit reports zero vulnerabilities.
- New Alembic migration upgrades/downgrades cleanly on a disposable SQLite database, preserving an existing captured payment and balances. Deployment/PostgreSQL migration remains a separate check.
- Computer-use checks on an isolated local preview passed AG Grid sorting, text/status/USD filters, filtered CSV export, Simple view actions, authenticated review-packet download, image upload/normalization, optional zero-cost input, and all four Safety Lab scenarios.
- The 390px request form scrolls without hiding its submit control. No model/provider calls were used for these local UI checks.
- Multimodal Gemini requests and fail-closed visual checks are covered by controlled-response tests. They do not establish deployed model accuracy. The existing 2:02 video predates these upgrades.

Screenshots and illustrative test evidence are in ignored local artifacts/upgrades/. The detailed implementation decisions and remaining checks are in docs/IDEA_REVIEW.md.
