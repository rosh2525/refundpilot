# Devpost submission draft

## Project name
RefundPilot

## Tagline
Evidence-backed refund decisions. Merchant-approved PayPal execution.

## Inspiration
A customer request, a merchant policy, and a payment record often live in different places. Small merchants need to understand the request and check the financial consequences before clicking refund. We built one desk that makes that decision understandable and keeps the merchant in control.

## What it does
RefundPilot links a customer message to its original payment. AI proposes a refund, denial, or further review with exact source quotations. Independent code checks USD amounts, the refund window, prior refunds, and reserved funds. The merchant approves a specific proposal; a durable worker executes that exact PayPal sandbox refund and reconciles its result.

## How we built it
React and TypeScript provide the merchant interface. FastAPI, Pydantic, SQLAlchemy, Alembic, and PostgreSQL support validation, immutable proposals, atomic reservations, durable jobs, and audit history. Gemini returns structured recommendations and optional photo observations. Photos remain unverified customer evidence. AG Grid Community supplies filterable records and CSV exports. An isolated Safety lab exposes approval invariants without provider calls, and a downloadable review packet provides a draft for merchant review. PayPal Orders v2 creates and captures test purchases; Payments v2 executes approved refunds and retrieves their status. Verified webhooks trigger reconciliation. Render hosts the container; Neon provides the PostgreSQL database.

## What makes it different
The recommendation is inspectable, approval is bound to exact financial parameters, and a lost network response cannot silently become a fresh refund. Pending and unknown outcomes stay visible and keep funds reserved. The product has a usable review interface rather than just a chat-to-API wrapper.

## Challenges
Handling uncertain provider outcomes, avoiding concurrent over-refunds, invalidating stale approvals, and keeping AI evidence grounded in supplied text and optional images without claiming authenticity.

## Accomplishments and validation
108 automated tests and 2 CSV security tests pass, and GitHub CI passes migration checks, the frontend build, and dependency auditing. The deployed Render app uses Neon PostgreSQL. A real PayPal sandbox $20 purchase was approved and captured, Gemini 3.5 Flash-Lite returned a structured $5 recommendation with verified source quotations, and the approved PayPal sandbox refund completed with $15 remaining. Actual signed capture and refund webhooks were verified. A request above the remaining balance was denied, and instruction injection produced a non-executable needs-review recommendation. See docs/VERIFICATION.md for completed checks and remaining acceptance work.

## What is next
A larger pilot with merchant feedback, additional currencies, controlled multi-merchant onboarding, and connected support systems. These are future work.

## Tools and attribution
PayPal sandbox REST APIs, Gemini API, React, TypeScript, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Render, and AI-assisted development tooling. The Northstar merchant, messages, and illustrations are original fictional demo material. Disclose the actual model and development tools used at submission.

## Testing instructions
Open https://refundpilot.onrender.com. Dedicated judge login and sandbox buyer credentials must be supplied privately in Devpost testing instructions before submission; they are intentionally absent from the public repository. Follow docs/SMOKE_TEST.md for checkout, capture, review, and refund steps. The free service may need time to wake after inactivity. Only sandbox test funds are supported.

## Required links
- Public source repository: https://github.com/rosh2525/refundpilot
- Hosted working demo: https://refundpilot.onrender.com
- Public YouTube video under 3 minutes: [insert after recording]
- License: MIT

Prepare materials in English. Target submission: 12 November 2026, 18:00 IST. Official deadline: 13 November 2026, 01:30 IST. Keep testing access until judging ends on 15 December.
