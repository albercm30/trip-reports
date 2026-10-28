# Trip Reports

A web app (SaaS) for wildlife and birding tour operators. Guides type or dictate a few notes and a rough species tally in the field; the app turns them into a polished, branded trip report for guests, and builds season insights the operator can use in marketing.

The product name is a placeholder: change `APP_NAME` to rename it everywhere.

## What it does

- **Accounts and teams:** sign-up with a free trial, log in, password reset, guide invites with seat limits, owner and guide roles.
- **Trips and days:** notes, place, date, photos (resized, location data stripped), and a species list per day. Everything saves as you type.
- **Species from rough notes:** “40 griffons, lynx x1!, heard eagle owl, warbler?” becomes rows with counts, highlights, heard-only and doubtful flags. Names are checked against the free GBIF taxonomy, which also fills in scientific names.
- **Understanding messy input:** typos, phone-dictation errors ("links" for lynx), number words in English and Spanish, counts before or after names, no commas, quick corrections ("3 no 4") and negations ("no lynx today"). The free parser uses a built-in English/Spanish/scientific species dictionary with typo tolerance and learns each operator's own species. With an AI key (free with Groq) the AI also reads species from the notes, and every species must quote the guide's own words or it is dropped, so nothing is ever invented.
- **Dictation:** a Dictate button on notes, tally and report boxes (browser speech recognition, free).
- **Drafting and spelling:** a free drafter builds the day report, opening and closing only from the guide's notes and species list. With an AI key the AI writes them instead, fixing spelling and dictation errors without changing facts, and a **Fix spelling** button proofreads text the guide wrote. Plan quotas apply and it falls back to the free drafter automatically.
- **Approval:** a guide approves each day; the report page shows what's missing before sending.
- **Reports:** branded (logo, colour, sign-off) in English, Spanish, German or French, with a day-by-day species table. Guests get a private, revocable link; print to PDF; sightings export as CSV.
- **Insights:** target-species success rates, best months per species, ready-to-copy website lines and a season summary.
- **Billing:** Stripe Checkout, Customer Portal and webhooks; read-only mode (with export) when a trial ends unpaid.
- **GDPR:** data export, account deletion, privacy and terms page templates.
- **Interface** in English and Spanish.

Stack: Python 3.12, FastAPI, SQLAlchemy, Alembic, Jinja templates with a little vanilla JavaScript, PostgreSQL (SQLite for local development).

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Open http://localhost:8000, sign up, then press **Add an example trip** and **Load a demo season**.

Run the tests with `pytest`.

## Go live for free

Everything below has a free tier and needs no paid service.

1. **Database:** create a free Postgres database at [Neon](https://neon.tech) and copy its connection string.
2. **Hosting:** in [Render](https://render.com), choose *New → Blueprint* and pick this repository (it reads `render.yaml`). Fill in `APP_URL` (your Render address) and `DATABASE_URL`. Photos are stored in the database (`STORAGE=db`), so no file storage is needed. The free web service sleeps when idle, so the first visit after a while takes ~30 seconds.
3. **Stripe (test mode first):**
   - Products → add **Starter** with prices €29/month and €290/year, and **Pro** with €59/month and €590/year. Copy each price ID (`price_…`) into the four `STRIPE_PRICE_…` variables.
   - Developers → API keys → copy the secret key into `STRIPE_SECRET_KEY`.
   - Developers → Webhooks → add endpoint `https://YOUR-APP/billing/webhook` with events `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`. Copy its signing secret into `STRIPE_WEBHOOK_SECRET`.
   - Settings → Billing → Customer portal: turn it on and allow cancelling and switching plans.
   - Test with card `4242 4242 4242 4242`. Switch to live keys and live prices when you're ready to charge.
4. **Legal pages:** set `LEGAL_NAME`, `LEGAL_ADDRESS`, `SUPPORT_EMAIL` (and `LEGAL_ID` for your NIF), and have the privacy and terms pages reviewed before taking real customers.

Free AI: create a key at console.groq.com (no card) and set `LLM_API_KEY` in Render. Optional later: `ANTHROPIC_API_KEY` for Claude, `BREVO_API_KEY` + `MAIL_FROM` for emailed resets and invites (Render's free tier blocks SMTP, so `SMTP_*` only works elsewhere), `STORAGE=s3` for S3 or Cloudflare R2 when photos outgrow the database.

## Project layout

```
app/
  main.py            app setup, security headers, error pages
  config.py          settings from environment variables
  models.py          database tables
  plans.py           plans, seats, AI quotas, trial and read-only rules
  security.py        passwords (scrypt), sessions, CSRF, rate limits
  routes/            pages and actions (auth, trips, reports, insights, team, billing, account)
  services/
    species.py       free tally parser
    taxonomy.py      GBIF name checks
    freedraft.py     free drafter
    ai.py            optional Claude drafting
    drafting.py      picks Claude or the free drafter
    reportdata.py    report tally, labels in 4 languages
    insights.py      season statistics
    billing.py       Stripe
    storage.py       photos: local, database or S3
    demo.py          example trip and demo season
  templates/, static/, locales/es.json
migrations/          Alembic
tests/               pytest suite
```

## Pilot companies

Set `ADMIN_EMAILS` to your login email. An **Admin** tab then lists every company that signed up; **Make pilot** gives a company everything free with no end date, and **End pilot** puts it back on a normal free trial.
