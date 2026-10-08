# Online MVP (v1.1) - deployment

## 1. Supabase secrets needed

Supabase project (free tier). Collect:

- `SUPABASE_URL`: Project Settings > API > Project URL
- `SUPABASE_ANON_KEY`: Project Settings > API > anon public key
- `DATABASE_URL`: Project Settings > Database > Connection string > Session pooler (URI, port 5432), with the DB password
- `ALLOWED_EMAILS`: comma-separated, exact match

Authentication > Providers > Email: enabled. Authentication > Sign In / Up: turn off "Allow new users to sign up".
Create each user under Authentication > Users > Add user (email + password, auto-confirm).

## 2. Schema

```
export DATABASE_URL='...'
psql "$DATABASE_URL" -f deploy/postgres_schema.sql
```

(Optional: `--apply` below also applies the same idempotent schema. Without psql, paste the file into the Supabase SQL Editor.)

## 3. Migration

```
pip install -r requirements.txt
python scripts/migrate_sqlite_to_postgres.py --dry-run
python scripts/migrate_sqlite_to_postgres.py --apply
```

Copies `runtime/deep_trekker.sqlite3` and the managed Price Master XLSX files into PostgreSQL. The SQLite file is
opened read-only. Check that the postgres counts match the sqlite counts and that the script prints `Central Price Master SHA-256 OK`. It is safe to re-run.

## 4. Streamlit Community Cloud

New app > this GitHub repo > branch `feat/v1.1-online-mvp` (switch to `main` after merge) > main file `app.py`.

## 5. Secrets to paste

App settings > Secrets: the four keys from `.streamlit/secrets.toml.example` with real values.
Optional: `TECHNICAL_CASE_PROVIDER` / `ANTHROPIC_API_KEY` as used locally.

## 6. First-login smoke test

1. Open the app URL: only the login form is shown.
2. Try an email that is not in `ALLOWED_EMAILS`: access is denied.
3. Log in with an allowed user: `ログイン中：<email>` is shown in the sidebar.
4. Home shows the migrated Technical Case / Quote. Price Master shows the 4 active masters (same SHA-256).
5. Quote 9701-MAG-4K at FX 165 gives a standard price of 6,432,000 JPY.
6. Open the same case in two browsers (A and B). Save in A, then save in B: B gets the conflict message, and A's change stays after reload.
7. Log out.

## 7. Rollback

- Cloud: delete the app in Streamlit Cloud (do not deploy `v1.0.0` online, because it has no login). Local v1.0.0 / v1.1 without `DATABASE_URL` keeps using SQLite.
- Data: the local `runtime/deep_trekker.sqlite3` is never modified by the migration and stays the v1 source.
- Central DB reset: drop the 7 tables in Supabase and re-run steps 2-3.
