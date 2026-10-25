# Setup

## Local preview

Follow the commands in the [README](../README.md). The default `.env.example` uses SQLite, fictional payment fixtures, and the local-only password `refundpilot-local`.

| Mode | Payments | Recommendations |
| --- | --- | --- |
| `preview` | Simulated; no PayPal calls | Gemini when configured, otherwise a labeled rule-based preview |
| `sandbox` | Actual PayPal sandbox checkout, capture, and refund APIs | Requires Gemini; unavailable AI blocks analysis |

For frontend development, run `npm --prefix frontend run dev`. Set `APP_URL` to the exact Vite origin so mutation requests pass the Origin check. Restore the deployed/backend origin for a production build.

## PayPal sandbox and Gemini

1. Create a [PayPal sandbox Business account and separate Personal buyer](https://developer.paypal.com/sandbox-testing/accounts).
2. Create a sandbox REST app owned by the Business account. Store its client ID and secret on the server.
3. Register `https://YOUR-APP/api/paypal/webhook` under that same REST app. Configure its webhook subscription ID as `PAYPAL_WEBHOOK_ID`.
4. Subscribe to `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.PENDING`, `PAYMENT.CAPTURE.REFUNDED`, `PAYMENT.CAPTURE.REVERSED`, `PAYMENT.REFUND.PENDING`, and `PAYMENT.REFUND.FAILED`.
5. Obtain a [Gemini API key](https://aistudio.google.com/) and set the server configuration below. Use fictional test messages and images.

```dotenv
PAYMENT_MODE=sandbox
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/refundpilot?sslmode=require
APP_URL=https://YOUR-APP
APP_PASSWORD=REPLACE_WITH_A_DEDICATED_PASSWORD
SESSION_SECRET=REPLACE_WITH_A_RANDOM_SECRET
PAYPAL_CLIENT_ID=YOUR_SANDBOX_CLIENT_ID
PAYPAL_CLIENT_SECRET=YOUR_SANDBOX_CLIENT_SECRET
PAYPAL_WEBHOOK_ID=YOUR_REGISTERED_WEBHOOK_ID
GEMINI_API_KEY=YOUR_GEMINI_KEY
GEMINI_MODEL=gemini-3.5-flash-lite
AI_DAILY_LIMIT=50
WORKER_ENABLED=true
```

Use an app password of at least 12 characters and a random session secret of at least 32 characters. Generate a secret with `python -c 'import secrets; print(secrets.token_urlsafe(48))'`. The default local password and session secret are rejected for sandbox/HTTPS deployments. Never commit credentials.

Run `alembic upgrade head` before starting sandbox mode. Preview fixtures are excluded from sandbox workflows. Follow the [integration test procedure](TESTING.md) after configuring the providers.

## Docker and hosting

The multi-stage [Dockerfile](../Dockerfile) builds the frontend and serves it from FastAPI. The startup command runs migrations, then starts one Uvicorn process and its asynchronous database-backed worker.

The [Render blueprint](../render.yaml) declares a free Docker web service. Use persistent PostgreSQL, such as Neon, and set the connection string with TLS enabled. Store environment secrets in the hosting dashboard. Render provides `RENDER_EXTERNAL_URL`; an explicit `APP_URL` overrides it. Set the health check to `/health`.

Free Render services can sleep after inactivity. Records and queued jobs remain in PostgreSQL; processing resumes after the service wakes. Keep full setup instructions available for reviewers. Do not run multiple Uvicorn workers without moving the in-memory login limiter to shared storage.

## Upload and usage limits

- One JPEG/PNG per case, up to 2 MiB and 12 megapixels; animation is rejected.
- Normalized images have metadata removed and a maximum edge of 1600 pixels.
- 20 image uploads per UTC day and 20 MiB aggregate image storage.
- 30 isolated safety simulations per UTC day.
- AI calls use `AI_DAILY_LIMIT` as well as provider quotas.

Images remain behind merchant authentication. Their bytes are excluded from dashboard JSON, CSV exports, and review packets. Images are sent to Gemini when analyzed. Once a case has an approved refund, its evidence cannot change.
