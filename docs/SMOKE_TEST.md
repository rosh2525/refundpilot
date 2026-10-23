# Actual integration acceptance test

This procedure requires configured PayPal sandbox accounts, Gemini, and the deployed PostgreSQL-backed application. Local tests and preview fixtures cannot satisfy it.

1. Record deployment URL, commit, mode, and model name, without copying secrets.
2. Confirm the app says **Sandbox workspace** and Gemini is configured. Sign in with the dedicated merchant password.
3. Open **Payments → Create $20 sandbox purchase**. Follow the provider approval link and use the separate sandbox Personal buyer account.
4. Return and select **I approved — capture payment**. Check that PayPal returns `COMPLETED`. Save the order and capture IDs in the private test log. If capture is pending, wait for reconciliation; do not call it completed.
5. Create the supplied cracked pen-holder request for $5. Analyze with Gemini. Verify that the source is the configured model, references are actual policy/customer quotations, and the exact proposed amount is $5.
6. Check the review confirmation and approve. Refreshing/clicking again must return the existing operation, not a second refund.
7. Wait for `COMPLETED`, which must be confirmed by the returned refund representation or GET refund. Check the merchant and buyer sandbox activity for the corresponding refund. The local remaining balance must be $15.
8. Verify an actual signed PayPal refund notification in the audit trail. Replay it using the PayPal dashboard's resend capability; no duplicate financial operation may appear.
9. Create a request above the remaining balance. It must be blocked before approval.
10. Create a message instructing the model to bypass approval or send funds to another account. Check that no refund executes without a human-approved fixed proposal and deterministic validation.
11. Redeploy/restart while an operation is pending or an isolated test job is leased. Confirm recovery keeps the same request UUID and does not duplicate movement. Do not intentionally interrupt an unrelated transaction.
12. Test the deployed app on a phone-width viewport. Check sign-in, request creation, review, approval, and history.

Record actual observed results. Mark untested steps honestly. Never label simulator notifications as actual payment events. Invalid signatures must remain rejected; do not add a public bypass for demonstrations.

Keep the hosted build, model access, merchant login, and sandbox buyer available through 15 December 2026. Give judges the dedicated login and buyer details through the submission testing instructions. Never publish merchant client secrets or model keys.
