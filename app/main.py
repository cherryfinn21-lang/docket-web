"""
Docket web backend — starter.

Run locally:
    uvicorn main:app --reload

This is deliberately a starter, not a finished production system. Before
you charge real people real money, at minimum add: email verification,
login rate-limiting, HTTPS-only cookies or secure token storage on the
frontend, a real Postgres database (not SQLite), structured logging, and a
privacy policy + terms of service page (required once you're handling
other people's personal data under UK GDPR).
"""
from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

import ai
import billing
import discovery
from auth import signup, login, create_token, get_current_user, require_credits, spend_credits
from config import CREDIT_COST_PARSE_CV, CREDIT_COST_TAILOR, CREDIT_COST_RANK, CREDIT_COST_DISCOVER
from db import init_db, get_session, User, CV, TailoredApplication, DiscoveryRun, Job
from schemas import (SignupRequest, LoginRequest, TokenResponse, ParseCVRequest, TailorRequest,
                      CheckoutRequest, RankRequest, DiscoverRequest)

app = FastAPI(title="Docket API")

# Lock this down to your real frontend domain before launch — "*" is only
# for local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

# Serve the frontend (app/static/index.html) from the same app, same origin
# — one deployment, no CORS headaches. API routes are defined below;
# anything not matching an API route falls through to the frontend.
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def route_index():
    return FileResponse("static/index.html")


# ---------------------------------------------------------------- auth
@app.post("/signup", response_model=TokenResponse)
def route_signup(body: SignupRequest, session: Session = Depends(get_session)):
    user = signup(session, body.email, body.password)
    return TokenResponse(access_token=create_token(user.id))


@app.post("/login", response_model=TokenResponse)
def route_login(body: LoginRequest, session: Session = Depends(get_session)):
    user = login(session, body.email, body.password)
    return TokenResponse(access_token=create_token(user.id))


@app.get("/me")
def route_me(user: User = Depends(get_current_user)):
    return {
        "email": user.email,
        "credits": user.credits,
        "subscription_active": bool(user.subscription_active),
    }


@app.delete("/me")
def route_delete_me(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """GDPR right-to-erasure endpoint. Cascades to their CVs and tailored
    applications via the foreign key relationships in db.py — if you add a
    new table holding user data, wire its cascade delete too."""
    session.delete(user)
    session.commit()
    return {"deleted": True}


# ---------------------------------------------------------------- CV
@app.post("/cv")
def route_parse_cv(body: ParseCVRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    require_credits(user, CREDIT_COST_PARSE_CV)
    structured = ai.parse_cv(body.raw_text)
    cv = CV(user_id=user.id, raw_text=body.raw_text, structured_json=__import__("json").dumps(structured))
    session.add(cv)
    spend_credits(session, user, CREDIT_COST_PARSE_CV)
    session.commit()
    session.refresh(cv)
    return {"cv_id": cv.id, "structured": structured}


@app.get("/cv")
def route_list_cvs(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    cvs = session.query(CV).filter(CV.user_id == user.id).order_by(CV.created_at.desc()).all()
    return [{"id": c.id, "created_at": c.created_at.isoformat()} for c in cvs]


# ---------------------------------------------------------------- discover (steps 2-4)
@app.post("/discover")
def route_discover(body: DiscoverRequest, background_tasks: BackgroundTasks,
                    user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """Steps 2-4: search a keyword across multiple job APIs, then rank every
    result against the CV. Runs in the background — this returns instantly
    with a run_id; poll GET /discover/{run_id} for progress, same idea as
    the local pipeline printing '[25/301] scored so far...' as it goes."""
    require_credits(user, CREDIT_COST_DISCOVER)
    cv = session.query(CV).filter(CV.id == body.cv_id, CV.user_id == user.id).first()
    if not cv:
        raise HTTPException(status_code=404, detail="CV not found.")

    run = DiscoveryRun(user_id=user.id, query=body.query, status="running")
    session.add(run)
    spend_credits(session, user, CREDIT_COST_DISCOVER)
    session.commit()
    session.refresh(run)

    background_tasks.add_task(
        discovery.run_discovery, run.id, user.id, body.cv_id, body.query, body.countries, body.sources
    )
    return {"run_id": run.id, "status": "running"}


@app.get("/discover/{run_id}")
def route_discover_status(run_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    run = session.query(DiscoveryRun).filter(DiscoveryRun.id == run_id, DiscoveryRun.user_id == user.id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {
        "status": run.status, "jobs_found": run.jobs_found,
        "jobs_scored": run.jobs_scored, "error": run.error,
    }


@app.get("/jobs")
def route_list_jobs(min_score: int = 0, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    jobs = session.query(Job).filter(
        Job.user_id == user.id, Job.triage_score.isnot(None), Job.triage_score >= min_score
    ).order_by(Job.triage_score.desc()).all()
    return [
        {"id": j.id, "title": j.title, "company": j.company, "location": j.location,
         "source": j.source, "url": j.url, "score": j.triage_score, "reason": j.triage_reason}
        for j in jobs
    ]


# ---------------------------------------------------------------- rank (step 4, manual-paste path)
@app.post("/rank")
def route_rank(body: RankRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """Step 4 via manually-pasted jobs, for when you'd rather paste specific
    postings than run a full /discover search."""
    require_credits(user, CREDIT_COST_RANK * len(body.jobs))
    cv = session.query(CV).filter(CV.id == body.cv_id, CV.user_id == user.id).first()
    if not cv:
        raise HTTPException(status_code=404, detail="CV not found.")

    import json
    cv_json = json.loads(cv.structured_json)
    results = []
    for job in body.jobs:
        ranked = ai.rank_job(cv_json, job.job_title, job.company, job.job_description)
        results.append({
            "job_title": job.job_title, "company": job.company,
            "score": ranked.get("score", 0), "reason": ranked.get("reason", ""),
        })
    spend_credits(session, user, CREDIT_COST_RANK * len(body.jobs))
    session.commit()
    results.sort(key=lambda r: r["score"], reverse=True)
    return {"ranked": results}


# ---------------------------------------------------------------- tailor (step 5+6)
@app.post("/tailor")
def route_tailor(body: TailorRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    require_credits(user, CREDIT_COST_TAILOR)
    cv = session.query(CV).filter(CV.id == body.cv_id, CV.user_id == user.id).first()
    if not cv:
        raise HTTPException(status_code=404, detail="CV not found.")

    if body.job_id is not None:
        job = session.query(Job).filter(Job.id == body.job_id, Job.user_id == user.id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        job_title, company, job_description = job.title, job.company, job.description
    elif body.job_title and body.company and body.job_description:
        job_title, company, job_description = body.job_title, body.company, body.job_description
    else:
        raise HTTPException(status_code=400, detail="Provide either job_id, or job_title+company+job_description.")

    import json
    cv_json = json.loads(cv.structured_json)
    tailored = ai.tailor_cv(cv_json, job_title, company, job_description)

    application = TailoredApplication(
        user_id=user.id, cv_id=cv.id, job_title=job_title, company=company,
        job_description=job_description, tailored_json=json.dumps(tailored),
        gaps_json=json.dumps(tailored.get("gaps", [])),
    )
    session.add(application)
    spend_credits(session, user, CREDIT_COST_TAILOR)
    session.commit()
    return {"application_id": application.id, "tailored": tailored}


@app.get("/applications")
def route_list_applications(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    apps = session.query(TailoredApplication).filter(TailoredApplication.user_id == user.id).order_by(
        TailoredApplication.created_at.desc()
    ).all()
    return [
        {"id": a.id, "job_title": a.job_title, "company": a.company, "created_at": a.created_at.isoformat()}
        for a in apps
    ]


# ---------------------------------------------------------------- billing
@app.post("/billing/checkout")
def route_checkout(body: CheckoutRequest, user: User = Depends(get_current_user)):
    url = billing.create_checkout_session(user, body.plan, body.success_url, body.cancel_url)
    return {"checkout_url": url}


@app.post("/webhooks/stripe")
async def route_stripe_webhook(request: Request, session: Session = Depends(get_session)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        billing.handle_webhook_event(payload, sig_header, session)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook error: {e}")
    return {"received": True}
