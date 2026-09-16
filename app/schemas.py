from pydantic import BaseModel, EmailStr


class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ParseCVRequest(BaseModel):
    raw_text: str


class TailorRequest(BaseModel):
    cv_id: int
    job_id: int | None = None  # tailor a job found via /discover or /jobs
    job_title: str | None = None    # ...or paste one manually instead
    company: str | None = None
    job_description: str | None = None


class JobToRank(BaseModel):
    job_title: str
    company: str
    job_description: str


class RankRequest(BaseModel):
    cv_id: int
    jobs: list[JobToRank]  # paste several at once — this is step 4 (rank out of 100)


class DiscoverRequest(BaseModel):
    cv_id: int
    query: str
    countries: list[str] = ["gb"]
    sources: list[str] = ["adzuna", "reed", "arbeitnow"]


class CheckoutRequest(BaseModel):
    plan: str  # "subscription" or "credits_20"
    success_url: str
    cancel_url: str
