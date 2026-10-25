# RefundPilot

**Thoughtful refunds. Clear decisions.**

A merchant refund desk that turns a customer request into an evidence-backed recommendation, checks deterministic refund policies, requires explicit approval, and tracks a PayPal sandbox refund to its confirmed outcome.

[Hosted app](https://refundpilot.onrender.com) · [Source](https://github.com/rosh2525/refundpilot)

Built for the 2026 PayPal AI Hackathon. React + TypeScript frontend, Python/FastAPI backend, PostgreSQL, PayPal Orders v2 / Payments v2, and Gemini structured output.

## Review workbench

- **Optional photo-assisted review:** upload one JPEG/PNG image for a case. The server verifies the actual format, rejects animation, caps input at 2 MiB / 12 megapixels, strips metadata, and scales to a maximum 1600px edge. Normalized bytes stay in PostgreSQL, behind authenticated access. Only use fictional test evidence; analysis sends the image to Gemini. A photo does not prove authenticity, ownership, SKU, fulfillment, or physical damage.
- **Grounded visual observations:** Gemini reports visible damage and consistency with the customer claim. Missing, unclear, contradictory, or no-visible-damage assessments cannot authorize a refund. Text citations and financial checks still apply. Evidence hashes are bound to proposals; changing an attachment invalidates older approvals.
- **Return handling estimate:** optional merchant-entered shipping and restocking costs are compared with the requested partial refund. The difference is not net margin or full-return savings; recovered item value, full refund, fees and replacement costs are excluded. Unknown inputs remain unknown.
- **AG Grid Community records:** Payments, Refund history, and Audit trail support sorting, text/USD filters, status filters, search, pagination, and CSV export with formula-prefix escaping. Simple views remain available. No Enterprise pivoting or paid license is required.
- **Safety lab:** authenticated, disposable simulations exercise the shared approval validator: five duplicate approvals, two competing $8 proposals against $10, an outdated policy hash, and a fixed blocked recommendation. These run in temporary SQLite with no provider/model calls or worker execution; they are not PostgreSQL or live PayPal stress tests. The ordinary request form also offers a fictional injection example for an actual AI review.
- **Review packet:** download a private JSON draft containing case information, proposal evidence, refund references, and audit events. It is not submitted to the PayPal Disputes API and does not independently establish delivery or eligibility.

The demo caps image uploads at 20 per UTC day, aggregate stored images at 20 MiB, and safety runs at 30 per UTC day. See [suggestion assessment](docs/IDEA_REVIEW.md) for what was implemented, deferred, or rejected and why.

## Two explicit operating modes

| Mode | Payments | Recommendation | Purpose |
| --- | --- | --- | --- |
| `preview` | Clearly labelled fictional payments and simulated refunds; no PayPal calls | Live Gemini if configured, otherwise explicitly labelled rule-based preview | Explore the interface without credentials |
| `sandbox` | Actual PayPal sandbox checkout, capture, and refund APIs | Requires a working Gemini key; there is no silent fallback | Integration testing and hackathon demonstration |

**Preview mode alone does not demonstrate the required PayPal + AI integration.** Complete the real sandbox smoke test before recording or submitting. Live payments are deliberately unsupported.

## Run locally

Prerequisites: Python 3.13, Node.js 22, npm, and Git. No GPU or model training is needed.

```sh
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
cd frontend
npm ci
npm run build
cd ..
alembic upgrade head
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and sign in with `refundpilot-local`. This password is only allowed for local preview. Three synthetic payments are seeded automatically. Click **New request**, retain the $5 example, inspect the review, check the explicit approval box, and approve the simulated refund. Check **Refund history** and **Audit trail**.

For UI development, run `npm run dev` from `frontend/` and use its Vite URL. Because state-changing requests verify the Origin, set `APP_URL` to that exact Vite URL while developing. Set it back to the backend/deployed origin for the production build. PayPal approval return URLs also use `APP_URL`.

## Enable actual PayPal sandbox + AI

1. Create a [PayPal developer account and sandbox accounts](https://developer.paypal.com/sandbox-testing/accounts): a Business merchant and a separate funded Personal buyer.
2. Under **Apps & Credentials → Sandbox**, create a REST app owned by the Business merchant. Keep its client secret on the server.
3. Deploy an HTTPS app endpoint. Register `https://YOUR-APP/api/paypal/webhook` under the **same** sandbox REST app. The subscription ID is the webhook ID; it is not the OAuth client ID.
4. Subscribe to `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.PENDING`, `PAYMENT.CAPTURE.REFUNDED`, `PAYMENT.CAPTURE.REVERSED`, `PAYMENT.REFUND.PENDING`, and `PAYMENT.REFUND.FAILED`.
5. Obtain a Gemini API key from [Google AI Studio](https://aistudio.google.com/). The default model is `gemini-3.5-flash-lite`; `GEMINI_MODEL` is configurable. Use synthetic data with the free tier. Model availability and rate limits must be checked on the account used for judging.
6. Set the server environment:

```dotenv
PAYMENT_MODE=sandbox
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/refundpilot?sslmode=require
APP_URL=https://YOUR-APP
APP_PASSWORD=YOUR_DEDICATED_JUDGE_PASSWORD_AT_LEAST_12_CHARACTERS
SESSION_SECRET=YOUR_RANDOM_SECRET_AT_LEAST_32_CHARACTERS
PAYPAL_CLIENT_ID=YOUR_SANDBOX_CLIENT_ID
PAYPAL_CLIENT_SECRET=YOUR_SANDBOX_CLIENT_SECRET
PAYPAL_WEBHOOK_ID=YOUR_REGISTERED_WEBHOOK_ID
GEMINI_API_KEY=YOUR_GEMINI_KEY
GEMINI_MODEL=gemini-3.5-flash-lite
AI_DAILY_LIMIT=50
WORKER_ENABLED=true
```

Generate a session secret locally with `python -c 'import secrets; print(secrets.token_urlsafe(48))'`, then put it directly in the hosting secret field. Do not commit secrets or paste them into issues or public submission text. Set a distinct merchant login password; the server rejects the default preview password on HTTPS or in sandbox mode.

7. Run `alembic upgrade head` before starting the sandbox application. Preview fixtures are hidden in sandbox mode and can never execute a real sandbox refund.
8. Complete the [real sandbox smoke test](docs/SMOKE_TEST.md). A simulator webhook is a mock event and cannot be verified with PayPal's postback verification endpoint. Simulator results do not prove that a refund occurred.

## Deploy

The multi-stage Dockerfile builds React and serves its static bundle from FastAPI. It runs migrations before starting one Uvicorn process. The same process hosts an asynchronous worker that polls durable database jobs; no Redis or separately billed worker is required. Do not deploy more than one Uvicorn worker without replacing the in-memory login limiter with shared storage.

The selected deployment uses **Render Free + Neon Free**, with no payment card and no paid resources. The `render.yaml` declaration defaults to the free web service.

1. Create a Neon **Free** project named `refundpilot`, choose a nearby AWS region, and copy its pooled PostgreSQL connection string with TLS enabled. No fixed trial expiry is required.
2. Create a Render **Docker Web Service** from this public Git repository. Select **Free**, Singapore region, and `/health` as its health check. Use manual deployment until the submission is stable.
3. Set `DATABASE_URL` to the Neon pooled connection string, `SESSION_SECRET` to a strong random secret, and `APP_PASSWORD` to a dedicated judge password. Render provides `RENDER_EXTERNAL_URL` automatically; the app uses it unless `APP_URL` is explicitly set.
4. Deploy initially with `PAYMENT_MODE=preview` if PayPal credentials are not ready. This is visibly a simulation. Register the actual webhook, configure Gemini and PayPal, and change to `sandbox` for integration verification.
5. Confirm `/health`, sign in, and run the full smoke test against the deployed PostgreSQL database.

Free web services sleep after inactivity and can take time to wake. Database records and queued jobs remain in Neon; the worker resumes when the web service wakes. PayPal retries unsuccessful webhook deliveries. Background browser tabs stop periodic dashboard polling to conserve free-tier usage. Ensure quotas and model access remain available through **15 December 2026**.

The Render workspace has a claimed $50 hackathon credit, but **using a credited paid instance still requires a card**. It is not required for this free deployment. A future optional paid configuration would be Starter web hosting ($7/month) plus a small persistent database, subject to explicit budget review. Do not enable a paid plan merely by copying an example.

No custom domain, paid database trial, or model training is required. AI usage has separate provider limits; start with its free tier. Keep the project-wide out-of-pocket ceiling at $30.

## Tests

```sh
pytest -q
alembic check
cd frontend
npm ci
npm run test:csv
npm run build
npm audit --audit-level=high
```

Tests use an isolated SQLite database and stub external provider responses. They exercise approval concurrency, idempotent retries, lost responses, pending/failed refunds, recovery leases, evidence checks, authentication, CSRF, and verified webhook deduplication. They do **not** replace an actual PayPal sandbox test or PostgreSQL deployment smoke test. CI runs the same checks on GitHub.

## How refunds stay controlled

- AI reads untrusted customer text and can only propose an outcome. It has no PayPal write tool or credentials in its input.
- Policy citations must be exact substrings of supplied documents; missing information stops AI-backed execution.
- Integer USD cents are checked against the requested amount, capture amount, confirmed refunds, active reservations, and the merchant's 30-day policy.
- An approval binds the proposal fingerprint, capture, exact amount, payment version, and policy version. Changed or superseded proposals cannot execute.
- An atomic compare-and-reserve prevents simultaneous proposals from spending the same balance. A unique operation prevents duplicate approval execution.
- The persisted `PayPal-Request-Id` and immutable payload are reused after ambiguous responses. A pending/unknown outcome keeps the amount reserved. Retry limits and an expiry boundary freeze unresolved operations for manual review rather than generating a new payment instruction.
- Database jobs use leases and recover after restarts. Settling a refund claims its reservation exactly once, including duplicate worker responses.
- Actual webhook signatures are checked through PayPal, deduplicated only after verification, and treated as reconciliation signals. They never authorize a refund. The worker fetches current provider state; event delivery order is not trusted.
- A successful HTTP request is not equivalent to a completed refund. The UI shows queued/executing/pending/completed/failed/unknown outcomes separately.

See [architecture](docs/ARCHITECTURE.md), [submission draft](docs/SUBMISSION.md), [demo script](docs/DEMO_SCRIPT.md), and [sample evaluation requests](fixtures/evaluation_cases.json).

## Boundaries

One merchant, app-created orders, USD, pasted text with optional image evidence, and explicit approval. No production payments, multi-merchant onboarding, payouts, dispute adjudication, real shipping integration, or email ingestion. Avoid making external refunds on app-owned demo captures; untracked provider changes require reconciliation. Customer messages and the example Northstar merchant are fictional.

MIT licensed. This project is an independent hackathon submission and does not imply PayPal endorsement.
