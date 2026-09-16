"""
Stripe billing — skeleton only. Before this works for real you need to:
  1. Create a Stripe account, get your real STRIPE_SECRET_KEY
  2. Create two Prices in the Stripe dashboard (subscription + one-off credit
     pack) and put their IDs in STRIPE_PRICE_ID_SUBSCRIPTION / _CREDITS_20
  3. Set up a webhook endpoint pointing at /webhooks/stripe and put its
     signing secret in STRIPE_WEBHOOK_SECRET
  4. Test with Stripe's test-mode keys and card numbers before going live
"""
import stripe
from sqlalchemy.orm import Session

from config import (
    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
    STRIPE_PRICE_ID_SUBSCRIPTION, STRIPE_PRICE_ID_CREDITS_20,
)
from db import User

stripe.api_key = STRIPE_SECRET_KEY


def create_checkout_session(user: User, plan: str, success_url: str, cancel_url: str) -> str:
    """plan: 'subscription' or 'credits_20'. Returns the Stripe Checkout URL
    to redirect the user's browser to."""
    if plan == "subscription":
        price_id, mode = STRIPE_PRICE_ID_SUBSCRIPTION, "subscription"
    elif plan == "credits_20":
        price_id, mode = STRIPE_PRICE_ID_CREDITS_20, "payment"
    else:
        raise ValueError(f"Unknown plan: {plan}")

    session = stripe.checkout.Session.create(
        customer=user.stripe_customer_id,  # None is fine — Stripe creates one
        customer_email=user.email if not user.stripe_customer_id else None,
        line_items=[{"price": price_id, "quantity": 1}],
        mode=mode,
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(user.id),  # how the webhook finds the user
        metadata={"plan": plan, "user_id": str(user.id)},
    )
    return session.url


def handle_webhook_event(payload: bytes, sig_header: str, session: Session):
    """Call this from the /webhooks/stripe route. Verifies the signature
    (never trust an unverified webhook body — anyone could POST anything),
    then applies the credit/subscription change."""
    event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)

    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        user_id = int(obj["metadata"].get("user_id", 0))
        plan = obj["metadata"].get("plan")
        user = session.query(User).get(user_id)
        if not user:
            return
        if not user.stripe_customer_id:
            user.stripe_customer_id = obj.get("customer")
        if plan == "credits_20":
            user.credits += 20
        elif plan == "subscription":
            user.subscription_active = 1
        session.commit()

    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.updated"):
        obj = event["data"]["object"]
        customer_id = obj.get("customer")
        user = session.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            active = obj.get("status") == "active"
            user.subscription_active = 1 if active else 0
            session.commit()
