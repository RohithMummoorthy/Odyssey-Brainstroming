# Google Sheets Setup Guide

This guide explains how to connect the Math Quiz platform to Google Sheets
so you can export final results with one click.

---

## Step 1 — Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click **Select a project** → **New Project**
3. Give it any name (e.g. "Math Quiz Export") → **Create**

---

## Step 2 — Enable Required APIs

With your project selected:

1. Go to **APIs & Services → Library**
2. Search for **"Google Sheets API"** → click it → **Enable**
3. Go back and search for **"Google Drive API"** → **Enable**

---

## Step 3 — Create a Service Account

1. Go to **IAM & Admin → Service Accounts**
2. Click **Create Service Account**
3. Name: `math-quiz-exporter` → **Create and Continue**
4. Skip role assignment → **Done**
5. Click the service account → **Keys** tab → **Add Key → Create new key → JSON**
6. The JSON file downloads automatically — **keep it private**

---

## Step 4 — Share Your Google Sheet

1. Create or open your results Google Sheet
2. Copy the **Sheet ID** from the URL:
   ```
   https://docs.google.com/spreadsheets/d/THIS_IS_THE_ID/edit
   ```
3. Click **Share** (top right)
4. Paste the service account email (find it in the downloaded JSON as `"client_email"`)
5. Set role to **Editor** → **Send**

---

## Step 5 — Set Environment Variables

### Local (`.env` file)

```env
GOOGLE_CREDS_JSON={"type":"service_account","project_id":"...","private_key_id":"...","private_key":"-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n","client_email":"math-quiz-exporter@your-project.iam.gserviceaccount.com",...}
GOOGLE_SHEET_ID=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
```

> **Important**: `GOOGLE_CREDS_JSON` must be the **entire JSON file content** as a **single line** with no extra wrapping.
>
> To convert the file to a single line (Linux/macOS):
> ```bash
> cat service-account-key.json | tr -d '\n'
> ```

### Render Dashboard

Set the same two values in **Render → Environment → Add Environment Variable**.

---

## Step 6 — Validate Setup

```bash
python scripts/setup_google_sheets.py
```

Expected output:
```
✓ GOOGLE_CREDS_JSON is valid JSON
✓ GOOGLE_SHEET_ID found
✓ Authentication successful
✓ Spreadsheet opened
✓ Results tab ready
✓ Audit Logs tab created
✓ Google Sheets ready.
```

---

## Troubleshooting

| Error | Fix |
|---|---|
| `SpreadsheetNotFound` | Share the sheet with the service account email (Step 4) |
| `json.JSONDecodeError` | Ensure GOOGLE_CREDS_JSON is valid JSON on one line |
| `invalid_grant` | Service account key may be revoked — create a new one |
| `PERMISSION_DENIED` | Drive API not enabled — complete Step 2 |
