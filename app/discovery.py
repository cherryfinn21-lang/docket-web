"""
Runs discovery + triage in the background after a user hits POST /discover.

This is the correct version of "their own terminal gets created": FastAPI's
BackgroundTasks runs this function after the HTTP response has already been
sent, so the request returns instantly and the work happens independently —
without actually spinning up a process per user. It's still fundamentally
one shared server doing work for many people, just not blocking any of them
on each other's requests.

Scaling note: BackgroundTasks runs in the same process as your web server,
which is fine for a handful of concurrent users. Once you have real traffic,
swap this for a proper task queue (Celery or RQ, with Redis) so discovery
jobs run in separate worker processes and a slow one can't starve the API of
resources — the function body below barely needs to change, just how it's
invoked.
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import ai
import sources
from db import SessionLocal, DiscoveryRun, Job, CV

TRIAGE_WORKERS = 10


def run_discovery(run_id: int, user_id: int, cv_id: int, query: str, countries: list[str], source_names: list[str]):
    session = SessionLocal()
    try:
        run = session.query(DiscoveryRun).get(run_id)
        cv = session.query(CV).get(cv_id)
        cv_json = json.loads(cv.structured_json)

        # --- discover (same sources.py as the local pipeline) ---
        found = []
        if "adzuna" in source_names:
            found += sources.fetch_adzuna(query, countries)
        if "reed" in source_names:
            found += sources.fetch_reed(query)
        if "arbeitnow" in source_names:
            found += sources.fetch_arbeitnow(query)

        seen_urls = set()
        job_rows = []
        for f in found:
            if f["url"] in seen_urls:
                continue
            seen_urls.add(f["url"])
            job = Job(
                user_id=user_id, discovery_run_id=run_id, source=f["source"],
                title=f["title"], company=f["company"], location=f["location"],
                country=f["country"], url=f["url"], description=f["description"],
            )
            session.add(job)
            job_rows.append(job)
        run.jobs_found = len(job_rows)
        session.commit()
        for j in job_rows:
            session.refresh(j)

        # --- triage, live + parallel, same approach as the local pipeline ---
        def _score_one(job_id):
            job = session.query(Job).get(job_id)  # fresh session per thread would be better; kept simple for a starter
            try:
                result = ai.rank_job(cv_json, job.title, job.company, job.description)
                return job_id, result, None
            except Exception as e:
                return job_id, None, str(e)

        job_ids = [j.id for j in job_rows]
        scored = 0
        with ThreadPoolExecutor(max_workers=TRIAGE_WORKERS) as pool:
            futures = [pool.submit(_score_one, jid) for jid in job_ids]
            for future in as_completed(futures):
                job_id, result, error = future.result()
                if result:
                    job = session.query(Job).get(job_id)
                    job.triage_score = result.get("score", 0)
                    job.triage_reason = result.get("reason", "")
                    scored += 1
                    session.commit()
                run.jobs_scored = scored
                session.commit()

        run.status = "done"
        session.commit()
    except Exception as e:
        run.status = "failed"
        run.error = str(e)
        session.commit()
    finally:
        session.close()
