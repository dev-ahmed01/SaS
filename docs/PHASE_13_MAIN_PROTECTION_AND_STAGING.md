# Phase 13 — Main Protection and Witnessed Staging Restoration

**No production deployment or live messaging is authorized by this procedure.**

## Main branch protection

On 13 October 2026, GitHub reports `dev-ahmed01/SaS` has no repository rulesets and `main.protected=false`.

The connected GitHub app cannot write repository-administration settings. The repository owner must activate the checked-in `ops/github/main-ruleset.json` with an **administration:write** credential. The proposed active ruleset applies solely to `refs/heads/main`, permits no bypass actors, requires one independent pull-request review and resolved conversations, dismisses stale approvals, requires passing `backend` and `frontend` checks, and blocks force pushes and deletions.

From `apps/api`, after this code merges:

```bash
python -m app.repository_ruleset check
# Set GITHUB_TOKEN locally using your GitHub admin authorization.
# Copy the current 40-character SHA of main from GitHub.
python -m app.repository_ruleset apply \
  --expected-main-sha <current-main-40-character-SHA> \
  --approve dev-ahmed01/SaS:main
python -m app.repository_ruleset check
```

The installer fails closed without token, exact confirmation or current SHA, and verifies the created ruleset using a separate read request. **No tokens should ever be pasted into a chat, committed or logged.** GitHub prohibits self-approval, so arrange an independent repository reviewer before turning on the one-review requirement.

## Staging restoration prerequisite

No identifiable SaS staging deployment was found in the connected Railway or Vercel project lists. Render required explicit workspace selection. No real Foundation backup, recovery database credentials or signed restore authorization was available. Do not pretend the CI synthetic restore is an approved staging restore.

The Foundation operator must first create a new, privately isolated and **empty** PostgreSQL recovery target named `sas_recovery_<unique-suffix>`, disconnect all outbound Meta/Pabbly services and disable schedulers, and independently restore a permitted encrypted staging backup. Never direct a restore against production or an already populated database. Use a separate SELECT-only account for verification.

From `apps/api`, after the isolated restore exists:

```bash
APP_ENV=staging \
SAS_RESTORE_TARGET_APPROVED=sas_recovery_20261013_audit \
SAS_RESTORED_TARGET_URL='<private-psycopg-URL-with-sslmode=verify-full>' \
python -m app.restored_staging_audit
```

The verifier accepts only a PostgreSQL recovery database with that exact confirmed name and TLS `sslmode=verify-full`. It executes read-only SQL, validates Alembic migration head, tenant-relationship integrity, collection-to-credit consistency, reversal-adjusted ledger equality, and disabled tenant automation. It prints aggregate counts only, not names, contacts, receipt references or secrets. It cannot start services, rewrite the database, dispatch messages or transfer money.

## Evidence and outstanding acceptance

A successful read-only audit is **not** proof of backup origin, encryption, recency, retention compliance, business RPO/RTO or live provider security. The operator and a separate reviewer must record approval, restored target isolation, backup provenance, measured restoration window, finance sampling, TLS, absence of outbound provider connections, and the approved business recovery objectives in a Foundation-controlled encrypted evidence system.

Keep the `docs/RELEASE_EVIDENCE_TEMPLATE.json` template unapproved until independently witnessed. See `docs/PHASE_13_PRODUCTION.md` and [release blocker #13](https://github.com/dev-ahmed01/SaS/issues/13). Do not commit filled evidence.
