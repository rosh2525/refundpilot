# RefundPilot

A refund review dashboard built for the **2026 PayPal AI Hackathon**. Gemini reviews customer requests against a merchant policy; the merchant approves the exact amount before the server submits a PayPal sandbox refund.

[Live app](https://refundpilot.onrender.com/) · [Setup](docs/SETUP.md) · [Architecture](docs/ARCHITECTURE.md) · [Testing](docs/TESTING.md)

## Workflow

1. Create a sandbox purchase and capture the buyer-approved payment.
2. Add a customer request, requested amount, and optional item photo.
3. Review the AI recommendation, source quotations, and financial checks.
4. Approve the specific proposal and track the refund to its confirmed outcome.
5. Inspect payment records, refund history, and the audit trail.

## Features

- **Policy review:** structured Gemini recommendations with checked quotations from the supplied policy, customer message, and payment facts.
- **Photo evidence:** optional JPEG/PNG uploads, metadata removal, authenticated storage, and visual observations. Inconclusive or contradictory evidence requires review; a photo cannot establish authenticity or ownership.
- **Approval controls:** integer USD cents, a 30-day policy, remaining-balance checks, proposal fingerprints, and atomic reservations.
- **Payment processing:** persistent request IDs, durable jobs, retries, verified webhooks, and provider status reconciliation. Pending and unknown outcomes remain reserved.
- **Records workbench:** AG Grid Community sorting, filtering, search, pagination, and CSV export with spreadsheet-formula escaping.
- **Review tools:** optional return-handling estimates and downloadable case packets. Estimates are not net-margin calculations; packets are drafts, not dispute submissions.
- **Safety lab:** isolated duplicate-approval, competing-proposal, stale-policy, and blocked-recommendation demonstrations. These use temporary SQLite state and make no PayPal or Gemini calls.

## Stack

| Layer | Technology |
| --- | --- |
| Frontend | React, TypeScript, Vite, AG Grid Community |
| Backend | Python 3.13, FastAPI, Pydantic, SQLAlchemy, Alembic |
| Database | PostgreSQL on Neon; SQLite for local preview and automated tests |
| Integrations | Gemini API, PayPal Orders v2, Payments v2, and webhooks |
| Deployment | Docker on Render; GitHub Actions for CI |

## Run locally

Requires Python 3.13 and Node.js 22.

```sh
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
npm --prefix frontend ci
npm --prefix frontend run build
alembic upgrade head
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open [localhost:8000](http://127.0.0.1:8000) and use `refundpilot-local` for the local preview. It seeds fictional payments and simulates refunds. Without a Gemini key, recommendations are explicitly labeled as rule-based previews. The [setup guide](docs/SETUP.md) explains how to enable real sandbox API calls.

## Validation

108 backend tests and 2 CSV security tests pass. CI checks tests, migrations, the frontend build, and dependency vulnerabilities. Hosted checks include completed sandbox refunds, verified payment notifications, image upload and an inconclusive image review, record exports, and all four safety simulations. See [testing notes](docs/TESTING.md) for coverage and remaining integration checks.

```sh
pytest -q
alembic check
npm --prefix frontend run test:csv
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=high
```

## Scope

RefundPilot supports one merchant, app-created payments, USD, and explicit approval. Live payments, automatic dispute responses, carrier verification, and multi-merchant onboarding are not supported. The hosted service uses sandbox funds and requires a merchant password; the free Render instance may take time to wake after inactivity.

Customer messages, images, and the sample Northstar merchant are fictional demo material. Images submitted for analysis are sent to Gemini. Keep credentials in server environment variables.

## License

[MIT](LICENSE)
