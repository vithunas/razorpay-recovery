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
    external_ref          text,
    name                 text not null,
    created_at           timestamptz not null default now()
);
create unique index if not exists merchant_external_ref_uniq
    on merchant(external_ref) where external_ref is not null;

-- ----------------------------------------------------------------------------
-- customer
-- ----------------------------------------------------------------------------
create table if not exists customer (
    id           uuid primary key default gen_random_uuid(),
    merchant_id  uuid not null references merchant(id) on delete cascade,
    external_ref text,                              -- Razorpay cust id / email / phone
    email        text,
    phone        text,
    name         text,
    created_at   timestamptz not null default now()
);
create unique index if not exists customer_external_ref_uniq
    on customer(external_ref) where external_ref is not null;
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
    customer_id       text,   -- external customer ref (Razorpay cust id / email / phone)
    merchant_id       text,   -- external merchant ref
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

-- ============================================================================
-- Migration 002 (folded in) — see db/migrations/002_action_log.sql
-- ============================================================================
alter table recovery_case add column if not exists source_event_id text;
alter table recovery_case add column if not exists policy_version   text;
alter table recovery_case add column if not exists last_proposal    jsonb;
alter table recovery_case add column if not exists last_decision    jsonb;

create unique index if not exists recovery_case_workflow_source_uniq
    on recovery_case(workflow_type, source_event_id)
    where source_event_id is not null;

create table if not exists action_log (
    id              uuid primary key default gen_random_uuid(),
    case_id         uuid references recovery_case(case_id) on delete cascade,
    customer_id     text,               -- external customer ref, matches recovery_case.customer_id
    actor           text not null,
    event           text not null,
    from_state      text,
    to_state        text,
    idempotency_key text,
    detail          jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now()
);
create index if not exists action_log_case_idx on action_log(case_id);
create index if not exists action_log_idem_idx on action_log(idempotency_key);
create index if not exists action_log_event_idx on action_log(event);
create index if not exists action_log_customer_idx on action_log(customer_id, created_at);

create unique index if not exists action_log_executed_idem_uniq
    on action_log(idempotency_key)
    where event = 'action_executed' and idempotency_key is not null;

create or replace function action_log_no_update() returns trigger as $$
begin
    raise exception 'action_log is append-only (UPDATE blocked)';
end;
$$ language plpgsql;

drop trigger if exists action_log_block_update on action_log;
create trigger action_log_block_update
    before update on action_log
    for each row execute function action_log_no_update();
