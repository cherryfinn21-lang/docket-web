"""
All secrets come from environment variables — never commit real keys.
See .env.example for what needs setting.
"""
import os

# --- Core ---
SECRET_KEY = os.environ.get("SECRET_KEY", "")            # JWT signing key — set a real random value in production
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./docket.db")  # swap to Postgres for real production
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")  # YOUR key — never sent to the browser, ever

# --- Stripe (billing) ---
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID_SUBSCRIPTION = os.environ.get("STRIPE_PRICE_ID_SUBSCRIPTION", "")  # Pro plan price ID from Stripe dashboard
STRIPE_PRICE_ID_CREDITS_20 = os.environ.get("STRIPE_PRICE_ID_CREDITS_20", "")      # 20-credit pack price ID

# --- Job sources (YOUR keys — used on behalf of every user; see README's
# ToS note before relying on this for real multi-user traffic) ---
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
REED_API_KEY = os.environ.get("REED_API_KEY", "")

# --- Models ---
TAILOR_MODEL = os.environ.get("TAILOR_MODEL", "claude-sonnet-5")
PARSE_MODEL = os.environ.get("PARSE_MODEL", "claude-sonnet-5")
TRIAGE_MODEL = os.environ.get("TRIAGE_MODEL", "claude-haiku-4-5-20251001")

# --- Credit costs per action ---
CREDIT_COST_PARSE_CV = 1
CREDIT_COST_RANK = 1  # per job ranked
CREDIT_COST_TAILOR = 2
CREDIT_COST_DISCOVER = 1  # flat fee per discover run — the triaging inside it is metered separately, see CREDIT_COST_RANK
FREE_SIGNUP_CREDITS = 3   # matches the "Free" plan in the demo

# --- JWT ---
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60 * 24 * 14  # 2 weeks

if not SECRET_KEY:
    raise RuntimeError("Set SECRET_KEY in your environment before running this — see .env.example")
