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


### Hosted upgrade smoke checks

Runtime source `3dacb8e` deployed successfully through the Render dashboard on 25 October 2026 (deploy `dep-dbet49qvcj2c73e30me0`). The service remains on Free. Health reports `{status: ok, mode: sandbox}`. The PostgreSQL migration completed on startup, and the existing $20 capture / $15 completed refunds / $5 available balance survived deployment.

A fictional $1 request (`9cd2731a-9ab1-4d26-b297-d54ada897e39`) uploaded an explicitly labeled illustrative PNG. The hosted app normalized/stored/retrieved it and Gemini returned a structured visual observation recognizing it was not a photograph of physical product damage. Both damage and consistency were inconclusive. The application returned needs_review with a blocking reason and no executable approval. No refund was approved for this request.

GitHub CI for the runtime source passed: https://github.com/rosh2525/refundpilot/actions/runs/40182664315. The existing demo video remains a valid earlier core-refund recording; it does not show these new features. Supported/contradictory photo accuracy, a new image-backed completed sandbox refund, and the original outstanding recovery/replay checks remain unverified.


The hosted AG Grid payment view loaded real sandbox records and exported a one-row CSV including captured/refunded/available/reserved balances. The hosted review-packet download preserved the attached evidence SHA, showed a blocked inconclusive proposal, included no image bytes, and contained zero refund operations for the new image case. All four hosted Safety Lab scenarios passed: five duplicate attempts produced one operation, two $8 proposals against $10 produced one reservation and one conflict, outdated policy was rejected, and the fixed needs-review example was rejected. These remain isolated SQLite simulations even when invoked from the hosted app; they do not establish PostgreSQL concurrency or provider behavior. Screenshots are in ignored artifacts/upgrades/live-*.png.
