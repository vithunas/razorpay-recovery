-- ============================================================================
-- Migration 003 — case/customer/merchant identity as external text refs
-- Run in the Supabase SQL editor. Idempotent.
--
-- Why: cases are born from Razorpay webhooks, which carry external ids
-- (cust_xxx, acc_xxx) or just an email/phone for guest checkouts — not our
-- internal UUIDs. The "unified customer-level view" (the product thesis) only
-- needs a STABLE KEY to group a customer's cases across all 3 workflows, not a
-- hard foreign key. The customer/merchant dimension tables stay for seed data
-- and dashboard enrichment; they join on these refs.
-- ============================================================================

-- recovery_case.customer_id / merchant_id -> text external refs
alter table recovery_case drop constraint if exists recovery_case_customer_id_fkey;
alter table recovery_case drop constraint if exists recovery_case_merchant_id_fkey;
alter table recovery_case alter column customer_id type text using customer_id::text;
alter table recovery_case alter column merchant_id type text using merchant_id::text;

-- action_log.customer_id -> text (matches recovery_case.customer_id for budget queries)
alter table action_log alter column customer_id type text using customer_id::text;

create index if not exists recovery_case_customer_ref_idx on recovery_case(customer_id);

-- customer / merchant dimension tables: add the external ref they'll be
-- looked up by, so seed data and dashboards can enrich a case's customer_id.
alter table customer add column if not exists external_ref text;
alter table merchant add column if not exists external_ref text;
create unique index if not exists customer_external_ref_uniq
    on customer(external_ref) where external_ref is not null;
create unique index if not exists merchant_external_ref_uniq
    on merchant(external_ref) where external_ref is not null;
