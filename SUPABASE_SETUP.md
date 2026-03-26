# Supabase Setup Guide

This guide walks you through creating and configuring the Supabase
database for the Math Quiz platform.

---

## Step 1 — Create a Supabase Project

1. Go to [supabase.com](https://supabase.com) → **New Project**
2. Choose a region close to your participants (e.g. South Asia → Singapore)
3. Set a strong database password → **Create new project**
4. Wait ~2 minutes for the project to initialize

---

## Step 2 — Create the Database Schema

1. Go to **SQL Editor** in the left sidebar
2. Click **New query**
3. Run `python scripts/seed_db.py` locally — it prints the full SQL
4. Paste and run the SQL in the Supabase editor
5. Also run these additional column migrations:

```sql
-- Additional columns added in Phases 4-5
ALTER TABLE teams ADD COLUMN IF NOT EXISTS screen_locked      BOOLEAN DEFAULT false;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS relogin_requested  BOOLEAN DEFAULT false;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS login_count        INTEGER DEFAULT 0;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS tab_switch_count   INTEGER DEFAULT 0;

-- Default configuration
INSERT INTO app_config (key, value) VALUES
  ('event_status',           'waiting'),
  ('event_duration_seconds', '1800'),
  ('allowed_ip',             '')
ON CONFLICT (key) DO NOTHING;
```

---

## Step 3 — Get Your API Keys

1. Go to **Settings → API** in your Supabase project
2. Copy:
   - **Project URL** → this is `SUPABASE_URL`
   - **`service_role` key** (NOT the `anon` key) → this is `SUPABASE_SERVICE_KEY`

> ⚠️ **Critical**: Always use the `service_role` key in your backend.
> The `anon` key is for unauthenticated frontend clients.
> The `service_role` key bypasses Row Level Security (RLS) — that's what you want for the quiz engine.

---

## Step 4 — Set Environment Variables

### Local (`.env` file)

```env
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Render Dashboard

Add the same two variables under **Environment → Add Environment Variable**.

---

## Step 5 — Validate Setup

```bash
python scripts/setup_supabase.py
```

Expected output:
```
✓ Credentials found
✓ Connected to: https://your-project.supabase.co
✓ Table 'teams' exists
✓ Table 'questions' exists
✓ Table 'sessions' exists
✓ Table 'audit_logs' exists
✓ Table 'app_config' exists
✓ Inserted default: event_status = 'waiting'
✓ Supabase ready.
```

---

## Row Level Security (RLS) Warning

Supabase enables RLS on new tables by default. Since the backend uses
the `service_role` key, RLS is **bypassed** — all data is accessible.

If you manually add RLS policies, test thoroughly to ensure
the service_role key still has full access.

To check RLS status:
- **Table Editor → Teams → RLS** — should show "RLS disabled" or confirm service_role bypass.

---

## Troubleshooting

| Error | Fix |
|---|---|
| `invalid JWT` | Wrong key — use service_role, not anon |
| All queries return empty | RLS is ON with no policies — disable RLS or add permissive policies |
| `relation "teams" does not exist` | Run the schema SQL in Step 2 |
| Connection timeout | Wrong `SUPABASE_URL` — verify it includes `https://` |
