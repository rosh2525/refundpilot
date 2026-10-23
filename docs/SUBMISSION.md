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
React and TypeScript provide the merchant interface. FastAPI, Pydantic, SQLAlchemy, Alembic, and PostgreSQL support validation, immutable proposals, atomic reservations, durable jobs, and audit history. Gemini returns structured recommendations. PayPal Orders v2 creates and captures test purchases; Payments v2 executes approved refunds and retrieves their status. Verified webhooks trigger reconciliation. Render hosts the container and database.

## What makes it different
The recommendation is inspectable, approval is bound to exact financial parameters, and a lost network response cannot silently become a fresh refund. Pending and unknown outcomes stay visible and keep funds reserved. The product has a usable review interface rather than just a chat-to-API wrapper.

## Challenges
Handling uncertain provider outcomes, avoiding concurrent over-refunds, invalidating stale approvals, and keeping AI evidence grounded in supplied text.

## Accomplishments and validation
[Replace this section with observed verification results before submission. Include the passing test count, real sandbox purchase/capture/refund IDs in an appropriate private test record, deployed PostgreSQL smoke results, and actual model output. Do not claim preview fixtures demonstrate PayPal integration.]

## What is next
A larger pilot with merchant feedback, additional currencies, controlled multi-merchant onboarding, and connected support systems. These are future work.

## Tools and attribution
PayPal sandbox REST APIs, Gemini API, React, TypeScript, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Render, and AI-assisted development tooling. The Northstar merchant, messages, and illustrations are original fictional demo material. Disclose the actual model and development tools used at submission.

## Testing instructions
[Insert hosted URL, dedicated merchant login, separate sandbox buyer access, clear checkout/refund steps, and limitations. Do not publish server secrets.]

## Required links
- Public source repository: https://github.com/rosh2525/refundpilot
- Hosted working demo: [insert verified URL]
- Public YouTube video under 3 minutes: [insert after recording]
- License: MIT

Prepare materials in English. Target submission: 12 November 2026, 18:00 IST. Official deadline: 13 November 2026, 01:30 IST. Keep testing access until judging ends on 15 December.
