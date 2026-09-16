# Docket web — backend starter

A real, deployable backend for the multi-user version of Docket: accounts,
credits/subscriptions via Stripe, CV upload and tailoring. Pairs with
whatever frontend you build (the published demo shows the UX; this is the
real API behind it).

## What this is, honestly

A **starter**, not a finished product. It's structured correctly (auth,
billing, data model, GDPR deletion) but several things are deliberately
left as stubs for you to finish before charging real money — each is
flagged with a comment in the code. The big ones:

- No email verification (anyone can sign up with any email string right now)
- No password reset flow
- No login rate-limiting (add this before launch — brute force matters)
- SQLite by default — fine for development, but switch `DATABASE_URL` to a
  real Postgres instance before real multi-user traffic (SQLite handles
  concurrent writers badly)
- CORS is wide open (`allow_origins=["*"]`) — lock this to your real
  frontend's domain before launch

## How multi-tenancy actually works here

Worth being explicit about, since it's easy to picture this wrong: there is
**one codebase and one database**, not separate code or processes per user.
Every row in `cvs`, `jobs`, and `tailored_applications` is stamped with a
`user_id`. Every route requires a valid login token, and every query filters
by `user.id` from that token — so a user's data is private because the
server never fetches anyone else's rows on their behalf, not because of any
separate storage or execution per person.

`/discover` is the one exception worth understanding: because searching
multiple job APIs and scoring every result takes real time (you've felt
this directly in the local pipeline), the route returns immediately with a
`run_id` and does the actual work via FastAPI's `BackgroundTasks` — the
work happens after the HTTP response is already sent, independently of
other requests. That's the correct version of "their own process handling
their request" without literally spinning up a terminal per person. At real
scale, swap `BackgroundTasks` for a proper task queue (Celery or RQ) so a
slow discovery run for one user can't compete with the API server itself
for resources — `discovery.py` is written so that swap doesn't need to
change much.

## What's ported directly from your proven local pipeline

- `sources.py` — the exact same Adzuna/Reed/Arbeitnow connectors
- `discovery.py` — discover + triage, same live-parallel approach that fixed
  the "hours not minutes" problem locally
- `ai.py` — the same no-fabrication tailoring rubric, JSON-repair logic, and
  the step-6 development-suggestions addition

The one real difference: these now run against **your** Adzuna/Reed keys on
behalf of every user, not each person's own. See the ToS note below — this
is exactly the point where that question stops being theoretical.

## Before you charge anyone money — three things to resolve first

1. **Job board terms of service.** Automatic discovery is now wired in and
   uses your own Adzuna/Reed keys for every user's searches. Their free
   tiers are typically for personal/single-app use — check their commercial
   terms before relying on this at real scale. (The `/rank` endpoint, where
   a user pastes their own job descriptions instead, sidesteps this
   entirely if you want a lower-risk path to launch.)
2. **UK GDPR.** Once strangers' CVs are in your database, you're a data
   controller. You need a privacy policy, and — this part's actually built
   — a working data-deletion endpoint (`DELETE /me`, already wired to
   cascade-delete everything). You may also need to register with the ICO
   depending on your setup; check gov.uk's current guidance.
3. **Stripe verification.** Before going live, Stripe needs your business
   details verified — this can take a few days, so start it early.

## Architecture

```
Browser (your frontend)
    │  HTTPS + JWT bearer token
    ▼
FastAPI backend (this repo)
    │
    ├── auth.py     — signup/login, password hashing, JWT
    ├── ai.py        — CV parsing + tailoring (YOUR Anthropic key, server-side only)
    ├── billing.py   — Stripe checkout + webhook handling
    ├── db.py        — SQLAlchemy models (User, CV, TailoredApplication)
    └── main.py      — routes tying it together
    │
    ▼
SQLite (dev) / Postgres (production)
```

**The one architectural rule that matters most**: your `ANTHROPIC_API_KEY`
lives only in this backend's environment variables, never in any frontend
code or API response. Every AI call happens server-side, triggered by an
authenticated request, metered against the user's credit balance. This is
different from the personal pipeline (which read your own key from your own
terminal) and different from the demo page (which uses each visitor's own
Claude session) — for a real paid product, it's your key, spent on your
users' behalf, which is exactly why metering (credits) has to be airtight.

## Deploying — step by step, to get an actual live URL

This gets you a real website, e.g. `https://docket-yourname.onrender.com`,
that anyone can visit. No Terminal commands needed for the deploy itself —
just GitHub's and Render's website dashboards.

1. **Put the code on GitHub.**
   - Go to github.com, create an account if you don't have one, click
     **New repository**, name it (e.g. `docket-web`), and create it.
   - On the new repo's page, click **Add file → Upload files**, then drag
     in everything from this folder (`app/`, `requirements.txt`,
     `.env.example`, `README.md`) — GitHub's uploader handles the folder
     structure. Commit the upload.
2. **Create a Render account.** Go to render.com, sign up — no credit card
   needed for the free tier.
3. **Create a Web Service.**
   - Click **New +** → **Web Service**, connect your GitHub account, and
     select the repo you just created.
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `cd app && uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Choose the **Free** instance type.
4. **Set your environment variables.** In the same setup screen (or under
   the service's **Environment** tab afterwards), add every variable from
   `.env.example` with real values — `SECRET_KEY` (make up a long random
   string), `ANTHROPIC_API_KEY`, your Adzuna/Reed keys, and Stripe keys once
   you have them (you can leave Stripe blank for now — billing just won't
   work yet, everything else still will).
5. **Click Deploy.** First deploy takes a few minutes. When it finishes,
   Render gives you a live URL — that's your website.

**Two things to know about the free tier**: a free web service "spins down"
after 15 minutes with no visitors and takes about a minute to wake back up
on the next visit — not broken, just cold-starting. And with the default
SQLite database, your data resets every time you redeploy (push new code) —
fine while you're testing, but switch `DATABASE_URL` to a real Postgres
instance (Render offers one, free for 30 days, then paid) before you have
real users you don't want to lose.

## Local setup (for testing changes before you deploy them)

```bash
cd docket-web
pip install -r requirements.txt
cp .env.example .env   # then fill in real values
export $(cat .env | xargs)   # or use a proper env loader
cd app
uvicorn main:app --reload
```

Visit `http://localhost:8000/docs` for interactive API docs (FastAPI
generates this automatically) — a good way to try each endpoint by hand
before wiring up a frontend.

## API summary

| Endpoint | Method | Needs auth | What it does |
|---|---|---|---|
| `/signup` | POST | No | Create account, get 3 free credits |
| `/login` | POST | No | Get a JWT token |
| `/me` | GET | Yes | Your email, credit balance, subscription status |
| `/me` | DELETE | Yes | Erase your account and all data (GDPR) |
| `/cv` | POST | Yes | Parse a pasted CV into structured JSON (1 credit) — step 1 |
| `/cv` | GET | Yes | List your saved CVs |
| `/discover` | POST | Yes | Search a keyword across job APIs + rank every result (background) — steps 2-4 |
| `/discover/{run_id}` | GET | Yes | Poll a discovery run's progress |
| `/jobs` | GET | Yes | List your discovered, ranked jobs |
| `/rank` | POST | Yes | Rank manually-pasted jobs instead (1 credit/job) — step 4, no discovery needed |
| `/tailor` | POST | Yes | Tailor a CV to a job — by `job_id` or pasted text (2 credits) — steps 5+6 |
| `/applications` | GET | Yes | List your tailored applications |
| `/billing/checkout` | POST | Yes | Get a Stripe Checkout URL |
| `/webhooks/stripe` | POST | No (Stripe-signed) | Applies credit/subscription changes |

## Deploying

For a first deploy, a platform that handles HTTPS and env vars for you —
Render, Railway, or Fly.io — is far less work than managing your own server.
All three have a free or near-free tier suitable for testing with real
users before you're spending money on infrastructure. Point `DATABASE_URL`
at a managed Postgres instance (most of these platforms offer one) rather
than SQLite once you deploy.

## Suggested build order

1. **Manual-paste MVP**: sign up, paste CV once, either paste job
   descriptions one at a time (`/rank` + `/tailor`) or run full discovery
   (`/discover`) once you're comfortable with the ToS question. Validates
   whether people will actually pay before you build anything more.
2. **Frontend**: a simple React or plain HTML/JS app calling this API — the
   published demo's HTML/CSS is a reasonable visual starting point to adapt,
   though it currently calls Claude directly rather than through this API.
3. **Move `/discover` onto a real task queue** once you have concurrent
   users — Celery or RQ with Redis, replacing `BackgroundTasks`.
4. **Polish**: email verification, password reset, rate limiting, proper
   logging/monitoring, terms of service + privacy policy pages.
