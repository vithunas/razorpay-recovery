-- ============================================================================
-- Migration 002 — append-only audit log + recovery_case pipeline columns
-- Run in the Supabase SQL editor. Idempotent.
-- ============================================================================

-- ---- recovery_case: pipeline bookkeeping -----------------------------------
alter table recovery_case add column if not exists source_event_id text;
alter table recovery_case add column if not exists policy_version   text;
alter table recovery_case add column if not exists last_proposal    jsonb;
alter table recovery_case add column if not exists last_decision    jsonb;

-- one open case per (workflow, source webhook event) — dedupe at the DB
create unique index if not exists recovery_case_workflow_source_uniq
    on recovery_case(workflow_type, source_event_id)
    where source_event_id is not null;

-- ---- action_log: append-only audit trail ----------------------------------
create table if not exists action_log (
    id              uuid primary key default gen_random_uuid(),
    case_id         uuid references recovery_case(case_id) on delete cascade,
    customer_id     uuid,               -- denormalized for contact-budget queries
    actor           text not null,      -- webhook | pipeline | policy | executor
    event           text not null,      -- state_transition | proposal | policy_decision
                                        -- | action_executed | action_reused | error
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

-- an action is executed at most once per (case, action): the executor's
-- idempotency guarantee, enforced at the DB so concurrent duplicates lose.
create unique index if not exists action_log_executed_idem_uniq
    on action_log(idempotency_key)
    where event = 'action_executed' and idempotency_key is not null;

-- Written log lines are immutable. UPDATE is blocked forever; DELETE is left
-- open so the Phase 6 demo-reset can wipe a run (cascade from recovery_case).
create or replace function action_log_no_update() returns trigger as $$
begin
    raise exception 'action_log is append-only (UPDATE blocked)';
end;
$$ language plpgsql;

drop trigger if exists action_log_block_update on action_log;
create trigger action_log_block_update
    before update on action_log
    for each row execute function action_log_no_update();
