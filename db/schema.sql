-- ============================================================================
-- AI Revenue Recovery Engine — schema
-- Phase 0: merchant, customer, webhook_event, recovery_case
-- Run this in the Supabase SQL editor (Project -> SQL Editor -> New query).
-- Safe to re-run: uses IF NOT EXISTS / idempotent guards.
-- ============================================================================

create extension if not exists "pgcrypto";  -- for gen_random_uuid()

-- ----------------------------------------------------------------------------
-- merchant
-- ----------------------------------------------------------------------------
create table if not exists merchant (
    id                   uuid primary key default gen_random_uuid(),
    razorpay_merchant_id text unique,
    name                 text not null,
    created_at           timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- customer
-- ----------------------------------------------------------------------------
create table if not exists customer (
    id           uuid primary key default gen_random_uuid(),
    merchant_id  uuid not null references merchant(id) on delete cascade,
    email        text,
    phone        text,
    name         text,
    created_at   timestamptz not null default now()
);
create index if not exists customer_merchant_idx on customer(merchant_id);

-- ----------------------------------------------------------------------------
-- webhook_event  (idempotency ledger — dedupe on X-Razorpay-Event-Id)
-- ----------------------------------------------------------------------------
create table if not exists webhook_event (
    id                 uuid primary key default gen_random_uuid(),
    event_id           text not null unique,          -- X-Razorpay-Event-Id header
    event_type         text,                          -- e.g. subscription.halted
    payload            jsonb not null,
    signature_verified boolean not null default false,
    processed          boolean not null default false,
    received_at        timestamptz not null default now(),
    processed_at       timestamptz
);
create index if not exists webhook_event_type_idx on webhook_event(event_type);

-- ----------------------------------------------------------------------------
-- recovery_case  (core abstraction, shared by all 3 workflows)
-- ----------------------------------------------------------------------------
create table if not exists recovery_case (
    case_id           uuid primary key default gen_random_uuid(),
    workflow_type     text not null
        check (workflow_type in ('mandate_whisperer', 'retry_router', 'collections_copilot')),
    customer_id       uuid references customer(id) on delete set null,
    merchant_id       uuid references merchant(id) on delete set null,
    amount_at_risk    bigint not null default 0,      -- paise, integer only
    reason            text not null,                  -- closed enum, enforced in app/policy
    evidence          jsonb not null default '{}'::jsonb,   -- refs to webhook_event rows
    cohort            text not null
        check (cohort in ('treatment', 'control')),  -- set at creation, never changed
    allowed_actions   jsonb not null default '[]'::jsonb,   -- resolved from policy, not the LLM
    attempted_actions jsonb not null default '[]'::jsonb,   -- append-only, timestamped
    state             text not null default 'DETECTED'
        check (state in (
            'DETECTED','ASSESSED','ELIGIBLE','INTERVENTION_SELECTED','POLICY_CHECK',
            'APPROVED','SUPPRESSED','EXECUTING','SUCCEEDED','FAILED',
            'RETRY','ESCALATE','STOP'
        )),
    outcome           text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);
create index if not exists recovery_case_customer_idx on recovery_case(customer_id);
create index if not exists recovery_case_state_idx on recovery_case(state);
create index if not exists recovery_case_cohort_idx on recovery_case(cohort);

-- keep updated_at fresh
create or replace function set_updated_at() returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists recovery_case_set_updated_at on recovery_case;
create trigger recovery_case_set_updated_at
    before update on recovery_case
    for each row execute function set_updated_at();
