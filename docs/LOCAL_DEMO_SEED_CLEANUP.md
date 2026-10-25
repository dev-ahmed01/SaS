# Local demo cleanup — preserve first prospect and Danny Danyal

This is for the **isolated localhost development PostgreSQL** `sas_dev`
database only. It does not access, modify, or purge production donor records.

## Scope

The original optional `seed_local_crm.py` creates 100 synthetic prospects,
10 synthetic promoters, 20 simulated payout obligations, four templates,
three unsent campaigns, two inactive automations and four sample pipeline
stages. No fake collection payment or WhatsApp send is created.

The cleanup selects only generated identities whose deterministic registration
IDs, synthetic phone patterns and notes match the original generator. It keeps:

- Generated **prospect #1** (the first item in the seed generator).
- The existing, exactly named **Danny Danyal** prospect, which must be found
  exactly once. It is **not** fabricated by the cleanup.
- Every promoter ever assigned to these two prospects or to any other
  non-generated prospect (even if an assignment has ended).
- Any other manually entered prospect or promoter.
- A pipeline stage still referenced by a retained prospect.
- All audit history.

It removes safely identified synthetic rows for the other demo prospects,
unreferenced demo promoters, fake payout plans, sample campaigns and
automations, unused demo templates and orphaned sample stages.

**Fail closed:** if Danny is missing/ambiguous, the first seed prospect
is absent, a synthetic identifier has been edited, a proposed removal has
financial/payment evidence, consent, receipt, message, recipient-review,
other dependent history or a sample campaign has an approval/preparation,
the entire cleanup refuses to make changes. It never silently deletes
legitimate payment, message or recipient activity.

## Run only on the local demo database

First take a local database backup using your existing local backup procedure,
then stop the development API while the cleanup runs. From `apps/api`,
with your existing virtual environment and loopback-only `.env`:

```powershell
python -m app.cleanup_local_seed
```

The default is **dry run** and reports the preservation/removal counts.
After verifying that the first generated prospect and Danny Danyal are
the intended retained records:

```powershell
python -m app.cleanup_local_seed --apply --confirm-synthetic-only
```

The code checks `APP_ENV=development`,
`LOCAL_DEMO_LOGIN_ENABLED=true`, the single demo Admin
`admin@local.sas.example`, the settings validator's exact loopback
PostgreSQL database, and disabled Pabbly/Saasyto messaging. There is no
production override flag.

## Preventing immediate reseeding

The legacy seeder no longer accepts just `--apply --confirm-synthetic-only`.
To repopulate the original 100 fake records it now requires an extra
`--allow-bulk-reseed` opt-in after a fresh local backup. Do not use that
option if you want the two retained prospects to remain the only demo
contacts.

## Important limitation

Editing the GitHub repository **does not execute the cleanup against your
Windows localhost database**. Run the dry-run and explicitly approved local
apply on the Windows machine containing the `sas_dev` database, or perform
the operation through a securely connected local operator. A hosted database
and any real Foundation records require a different reviewed migration;
this utility refuses to target them.

## Saasyto integration after cleanup

The cleanup does not enable WhatsApp. Refer to
[SAASYTO_CAMPAIGN_INTEGRATION.md](SAASYTO_CAMPAIGN_INTEGRATION.md)
for the separate credential, sender approval, fresh campaign review,
private worker and consent-gated smoke-test requirements.
