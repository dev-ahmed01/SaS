# Delivery and acceptance gates

Work on feature branches. Each phase requires a PR, documented verification, tests for changed behavior, and a reviewer decision before merging. `main` is not a staging environment.

| Phase | Scope | Acceptance |
| --- | --- | --- |
| 01 | Repo, API, typed configuration, initial DB migration, design tokens, CI | Health checks, schema tests and migration roundtrip pass |
| 02 | Approved UI system and desktop navigation | Visual regression / accessibility checks |
| 03 | Admin auth, provisioning, audited configurable settings | No unauthenticated access, no default passwords |
| 04 | Prospects and optional UPI IDs | Create/search/edit/status tests |
| 05 | Promoters and sponsor linking | Assigned-sponsor visibility and edit tests |
| 06 | Monthly accounting in IST, inactivity/reactivation | Boundary and partial-payment tests |
| 07 | Bank-neutral CSV/Excel importer | Invalid-file and duplicate import tests |
| 08 | Bank-specific parsing, UPI reconciliation, Collections | Await bank example; unmatched queue, idempotency |
| 09 | Recurring and one-time Payouts | No fake payment execution, financial audit |
| 10 | Reminder eligibility engine and queue | No messages to inactive/paid sponsors |
| 11 | Pabbly and WhatsApp, 5th/20th workflows | Await onboarding, opt-in, approved templates |
| 12 | Dashboard from real records | Accurate reconciled totals |
| 13 | Staging, UAT, monitoring, backups and production | Restore drill, QA and sign-off |

## Phase 01 explicitly excluded

No login that could be mistaken for real authentication; no Admin user seeds; no real donor records; no bank parsing, Pabbly or messaging credentials; no Dashboard financial KPIs. Early migrations contain only organizations, Admin users, organization settings and audit events. Later tables must arrive through separate reviewed migrations.

## Open technical hardening before production

- Pin GitHub Actions to verified immutable commit SHAs.
- Generate and commit a frontend package lock, switch CI to `npm ci`.
- Integrate secret scanning, dependency audit, lint/accessibility/browser tests, PostgreSQL integration tests and migrations drift check.
- Introduce structured authorization tests, append-only audit protections, encrypted backups with restoration evidence, and incident/runbook documentation.
