"""
Job discovery via official, ToS-compliant APIs only — ported directly from
the proven local pipeline. Same sources, same reasoning: we don't scrape
LinkedIn/Indeed/Glassdoor since all three prohibit it in their terms.

IMPORTANT DIFFERENCE FROM THE LOCAL VERSION: these calls now use YOUR keys
(ADZUNA_APP_ID etc. in config.py) on behalf of every signed-up user, not
each person's own keys. Adzuna and Reed's free tiers are typically licensed
for personal/single-app use — check their commercial terms before relying
on this for real multi-user traffic (see README).
"""

import requests

from config import ADZUNA_APP_ID, ADZUNA_APP_KEY, REED_API_KEY

REQUEST_TIMEOUT = 20


def _normalise(source, title, company, location, country, url, description, salary="", posted_date=""):
    return {
        "source": source,
        "title": title or "",
        "company": company or "",
        "location": location or "",
        "country": country or "",
        "url": url,
        "description": (description or "")[:4000],
        "salary": salary or "",
        "posted_date": posted_date or "",
    }


def fetch_adzuna(query, countries, results_per_page=50, max_pages=2):
    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        return []
    results = []
    for country in countries:
        for page in range(1, max_pages + 1):
            url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
            params = {
                "app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
                "results_per_page": results_per_page, "what": query,
                "content-type": "application/json",
            }
            r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                break
            hits = r.json().get("results", [])
            if not hits:
                break
            for h in hits:
                results.append(_normalise(
                    "adzuna", h.get("title"), (h.get("company") or {}).get("display_name"),
                    (h.get("location") or {}).get("display_name"), country.upper(),
                    h.get("redirect_url"), h.get("description"),
                    salary=str(h.get("salary_min", "")), posted_date=h.get("created", ""),
                ))
    return results


def fetch_reed(query, location="", results_per_page=100, max_pages=2):
    if not REED_API_KEY:
        return []
    results = []
    for page in range(max_pages):
        params = {"keywords": query, "locationName": location, "resultsToTake": results_per_page,
                   "resultsToSkip": page * results_per_page}
        r = requests.get("https://www.reed.co.uk/api/1.0/search", params=params,
                          auth=(REED_API_KEY, ""), timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            break
        hits = r.json().get("results", [])
        if not hits:
            break
        for h in hits:
            results.append(_normalise(
                "reed", h.get("jobTitle"), h.get("employerName"), h.get("locationName"), "GB",
                h.get("jobUrl"), h.get("jobDescription"),
                salary=f"{h.get('minimumSalary','')}-{h.get('maximumSalary','')}", posted_date=h.get("date", ""),
            ))
    return results


def fetch_arbeitnow(query=""):
    results = []
    r = requests.get("https://www.arbeitnow.com/api/job-board-api", timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        return []
    hits = r.json().get("data", [])
    q = query.lower()
    for h in hits:
        title = h.get("title", "")
        if q and q not in title.lower() and q not in (h.get("description") or "").lower():
            continue
        results.append(_normalise(
            "arbeitnow", title, h.get("company_name"),
            ", ".join(h.get("locations", []) or [h.get("location", "")]), "EU",
            h.get("url"), h.get("description"), posted_date=str(h.get("created_at", "")),
        ))
    return results


SOURCES = {"adzuna": fetch_adzuna, "reed": fetch_reed, "arbeitnow": fetch_arbeitnow}
