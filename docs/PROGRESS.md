# Build progress

Architectural law: **AI PROPOSES → CODE DECIDES → CODE EXECUTES**

| Phase | Status | Notes |
|-------|--------|-------|
| 0 — Foundations | ✅ complete | Real Razorpay test webhook round-trips into Supabase `webhook_event` |
| 1 — Deterministic backbone (stubbed brain) | ✅ complete | event→case→policy→executor→audit proven; 28 tests + live smoke |
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

## Phase 1 — Definition of Done

> (a) duplicate webhook delivery → only one action fires
> (b) an intentionally out-of-policy stub proposal → executor never fires, rejection logged

**Both met.** 28 unit tests (`pytest -q`) + a live run of `scripts/phase1_smoke.py`
against real Supabase + Razorpay Test Mode on 2026-09-02:

- signed synthetic `payment.failed` → case `136c06df…` walked
  `DETECTED→ASSESSED→ELIGIBLE→INTERVENTION_SELECTED→POLICY_CHECK→APPROVED→EXECUTING→SUCCEEDED`
- policy APPROVED at ground-truth amount ₹427.00 (no clamp needed)
- executor created a **real** Test Mode payment link `https://rzp.io/rzp/tiFuhch`
- delivered twice + reprocessed twice more → **1** `action_executed`, **1** attempted action, **1** case
- `tests/test_phase1_dod.py::test_out_of_policy_proposal_never_reaches_executor`:
  rogue proposal (`send_whatsapp_nudge` for retry_router) → case `SUPPRESSED`,
  gateway call count 0, `policy_decision` logged with `approved=false`

### Components
| module | role |
|--------|------|
| `app/security.py` | HMAC-SHA256 webhook signature verify (constant-time); tested vs a real captured payload |
| `app/models.py` | closed enums + `InterventionProposal` / `PolicyDecision` / `RecoveryCase` |
| `app/state_machine.py` | `ALLOWED_TRANSITIONS`; `SUPPRESSED` is terminal and ≠ `FAILED` |
| `policy/policy_config.v1.toml` + `app/policy.py` | versioned limits, allowlist, ground-truth amount + clamps, contact budget, escalation ceiling |
| `app/agents.py` | **stubbed brain** — fixed schema-valid proposal, exact signature Phase 2's Gemini agent replaces |
| `app/executor.py` | only module that calls Razorpay; idempotent on `(case_id, action)` |
| `app/audit.py` / `app/cases.py` / `app/pipeline.py` | orchestration + append-only `action_log` |
| `app/webhooks.py` | verify → dedupe-insert → `BackgroundTasks` enqueue |

### Known slow spot (revisit Phase 3)
The background pipeline does ~1 Supabase PATCH + 1 INSERT per state transition
(~10–20 s wall time from this location). The webhook ACK itself is still fast
(<5 s) because work is deferred to `BackgroundTasks`. Phase 3 hardening may
batch transition writes.

## Local run (dev)

```bash
venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
ngrok http 8000        # public URL -> Razorpay Dashboard > Settings > Webhooks
```

Webhook URL registered: `https://<ngrok-subdomain>.ngrok-free.dev/webhook/razorpay`
(ngrok free subdomains change on restart — update the Razorpay webhook when it does).

### Known test rows to clear later (Phase 6 reset)
`evt_p0_live_1788267001`, `evt_route_selftest` in `webhook_event`.
