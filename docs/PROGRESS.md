# Build progress

Architectural law: **AI PROPOSES → CODE DECIDES → CODE EXECUTES**

| Phase | Status | Notes |
|-------|--------|-------|
| 0 — Foundations | ✅ complete | Real Razorpay test webhook round-trips into Supabase `webhook_event` |
| 1 — Deterministic backbone (stubbed brain) | ⬜ not started | |
| 2 — Real AI + MandateWhisperer live | ⬜ | needs a Razorpay Plan + Subscription (Subscriptions product confirmed enabled) |
| 3 — Failure injection & resilience | ⬜ | |
| 4 — Retry Router + Collections Copilot | ⬜ | |
| 5 — Metrics & evaluation | ⬜ | |
| 6 — API contract freeze + demo rig | ⬜ | |
| 7 — Frontend | ⬜ | |
| 8 — Polish & rehearsal | ⬜ | |

---

## Phase 0 — Definition of Done

> A real Razorpay test webhook round-trips into a DB row.

**Met.** On 2026-09-01, a Test Mode Payment Link payment produced real webhook
deliveries from `Razorpay-Webhook/v1` to the ngrok-tunnelled FastAPI app, each
persisted to `webhook_event`:

| received | event | payment entity |
|----------|-------|----------------|
| 18:12:52 | `payment.authorized` | `pay_TWro3urB7B31n4` |
| 18:12:52 | `order.paid` | `pay_TWro3urB7B31n4` |
| 18:12:56 | `payment.captured` | `pay_TWro3urB7B31n4` |
| 18:12:57 | `payment_link.paid` | `pay_TWro3urB7B31n4` |

- Dedupe key: `X-Razorpay-Event-Id` → `webhook_event.event_id` UNIQUE.
- `X-Razorpay-Signature` header confirmed present on real deliveries
  (verification is Phase 1, currently stored as `signature_verified = false`).
- Razorpay retry/backoff observed working: initial deliveries 404'd on a route
  mismatch, Razorpay redelivered, later attempts 200'd — no manual replay.

## Local run (dev)

```bash
venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
ngrok http 8000        # public URL -> Razorpay Dashboard > Settings > Webhooks
```

Webhook URL registered: `https://<ngrok-subdomain>.ngrok-free.dev/webhook/razorpay`
(ngrok free subdomains change on restart — update the Razorpay webhook when it does).

### Known test rows to clear later (Phase 6 reset)
`evt_p0_live_1788267001`, `evt_route_selftest` in `webhook_event`.
