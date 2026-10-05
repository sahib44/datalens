"""PostgreSQL job worker with fenced claims and atomic result persistence."""

from datetime import timedelta
from threading import Event, Thread
import time
import logging
from sqlalchemy import select, or_, and_, update, delete
from .db import Session, STORAGE
from .models import (
    Job,
    Version,
    Analysis,
    ColumnProfile,
    Finding,
    Comparison,
    Cleanup,
    now,
    uid,
)
from .profiling import parse_csv, profile, Config, InputError
from .comparison import compare

LEASE_SECONDS = 300
logger = logging.getLogger("datalens.worker")


def claim():
    with Session.begin() as s:
        job = s.scalar(
            select(Job)
            .where(
                or_(
                    Job.status == "queued",
                    and_(Job.status == "running", Job.lease_until < now()),
                )
            )
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.stage = "failed"
            job.finished_at = now()
            job.error_code = "attempts_exhausted"
            job.error_message = "Processing stopped after repeated failures."
            return None
        job.status = "running"
        job.stage = "parsing"
        job.attempts += 1
        job.started_at = now()
        job.claim_token = uid()
        job.lease_until = now() + timedelta(seconds=LEASE_SECONDS)
        job.error_code = None
        job.error_message = None
        return job.id, job.claim_token


def heartbeat(job_id, token, stop):
    while not stop.wait(30):
        try:
            with Session.begin() as s:
                s.execute(
                    update(Job)
                    .where(
                        Job.id == job_id,
                        Job.claim_token == token,
                        Job.status == "running",
                    )
                    .values(lease_until=now() + timedelta(seconds=LEASE_SECONDS))
                )
        except Exception:
            logger.warning("Heartbeat unavailable for job %s", job_id)


def stage(job_id, token, value):
    with Session.begin() as s:
        s.execute(
            update(Job)
            .where(Job.id == job_id, Job.claim_token == token, Job.status == "running")
            .values(stage=value)
        )


def load_analysis(s, version_id):
    a = s.scalar(select(Analysis).where(Analysis.version_id == version_id))
    if a is None:
        raise InputError("A comparison requires two completed analyses.")
    return {
        "engine_version": a.engine_version,
        "configuration": a.configuration,
        "summary": a.summary,
        "limitations": a.limitations,
        "created_at": a.created_at.isoformat(),
        "columns": [
            c.result
            for c in s.scalars(
                select(ColumnProfile)
                .where(ColumnProfile.analysis_id == a.id)
                .order_by(ColumnProfile.position)
            )
        ],
    }


def process(job_id, token):
    stop = Event()
    thread = Thread(target=heartbeat, args=(job_id, token, stop), daemon=True)
    thread.start()
    try:
        with Session() as s:
            job = s.get(Job, job_id)
            if not job or job.claim_token != token or job.status != "running":
                return
            if job.kind == "profile":
                v = s.get(Version, job.version_id)
                h, rows = parse_csv(STORAGE / v.storage_key)
                stage(job_id, token, "profiling")
                result = profile(h, rows, Config(**v.configuration))
            else:
                c = s.get(Comparison, job.comparison_id)
                a, b = s.get(Version, c.baseline_id), s.get(Version, c.candidate_id)
                ah, ar = parse_csv(STORAGE / a.storage_key)
                bh, br = parse_csv(STORAGE / b.storage_key)
                stage(job_id, token, "comparing")
                result = compare(
                    ah, ar, bh, br, load_analysis(s, a.id), load_analysis(s, b.id)
                )
        stage(job_id, token, "saving results")
        with Session.begin() as s:
            job = s.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if not job or job.claim_token != token or job.status != "running":
                return
            if job.kind == "profile":
                # Replacement is atomic and bounded by unique(version_id).
                s.execute(delete(Analysis).where(Analysis.version_id == job.version_id))
                a = Analysis(
                    version_id=job.version_id,
                    engine_version=result["engine_version"],
                    configuration=result["configuration"],
                    summary=result["summary"],
                    limitations=result["limitations"],
                )
                s.add(a)
                s.flush()
                for col in result["columns"]:
                    s.add(
                        ColumnProfile(
                            analysis_id=a.id,
                            position=col["position"],
                            name=col["name"],
                            result=col,
                        )
                    )
                for f in result["findings"]:
                    s.add(
                        Finding(
                            analysis_id=a.id,
                            check_id=f["check_id"],
                            severity=f["severity"],
                            column_name=f["column"],
                            result=f,
                        )
                    )
                v = s.get(Version, job.version_id)
                v.row_count = result["summary"]["rows"]
                v.column_count = result["summary"]["columns"]
            else:
                s.get(Comparison, job.comparison_id).result = result
            job.status = "completed"
            job.stage = "complete"
            job.finished_at = now()
            job.lease_until = None
    except Exception as exc:
        # Avoid logging values or tracebacks that could contain uploaded data.
        with Session.begin() as s:
            job = s.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if job and job.claim_token == token and job.status == "running":
                terminal = (
                    isinstance(exc, InputError) or job.attempts >= job.max_attempts
                )
                job.status = "failed" if terminal else "queued"
                job.stage = job.status
                job.error_code = (
                    "invalid_data"
                    if isinstance(exc, InputError)
                    else "processing_error"
                )
                job.error_message = (
                    str(exc)
                    if isinstance(exc, InputError)
                    else "Processing failed. Automatic retries are limited to three attempts."
                )
                job.finished_at = now() if terminal else None
                job.lease_until = None
    finally:
        stop.set()
        thread.join(timeout=2)


def cleanup_files():
    with Session.begin() as s:
        for item in s.scalars(
            select(Cleanup).with_for_update(skip_locked=True).limit(100)
        ):
            (STORAGE / item.storage_key).unlink(missing_ok=True)
            s.delete(item)


def run_once():
    cleanup_files()
    claimed = claim()
    if claimed:
        process(*claimed)
    return bool(claimed)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    STORAGE.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            if not run_once():
                time.sleep(1)
        except Exception:
            logger.warning("Worker temporarily cannot access its resources; retrying.")
            time.sleep(3)
