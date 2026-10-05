import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from starlette.exceptions import HTTPException
from .db import Session, STORAGE
from .models import Dataset, Version, Job, Analysis, Finding, Comparison, Cleanup
from .profiling import Config, InputError, parse_csv, MAX_BYTES
from .worker import load_analysis, cleanup_files


@asynccontextmanager
async def lifespan(app):
    STORAGE.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="DataLens API", version="0.1.0", lifespan=lifespan)


class APIError(Exception):
    def __init__(self, status, code, message, details=None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def error(request, status, code, message, details=None):
    return JSONResponse(
        status_code=status,
        content=dict(
            code=code,
            message=message,
            details=details,
            request_id=getattr(request.state, "request_id", "unknown"),
        ),
    )


@app.middleware("http")
async def request_id(request, call_next):
    request.state.request_id = str(uuid4())
    try:
        response = await call_next(request)
    except Exception:
        return error(
            request, 500, "internal_error", "An unexpected server error occurred."
        )
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(APIError)
async def api_error(request, exc):
    return error(request, exc.status, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return error(
        request,
        422,
        "invalid_request",
        "Check request fields and parameter limits.",
        [{"field": list(e["loc"]), "message": e["msg"]} for e in exc.errors()],
    )


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return error(request, exc.status_code, "http_error", str(exc.detail))


def require(s, model, id):
    item = s.get(model, id)
    if item is None:
        raise APIError(404, "not_found", "The requested resource does not exist.")
    return item


def job_json(j):
    return {
        k: getattr(j, k)
        for k in [
            "id",
            "kind",
            "status",
            "stage",
            "attempts",
            "max_attempts",
            "created_at",
            "started_at",
            "finished_at",
            "error_code",
            "error_message",
        ]
    }


def version_json(v, j=None):
    return dict(
        id=v.id,
        dataset_id=v.dataset_id,
        filename=v.filename,
        sha256=v.sha256,
        size=v.size,
        created_at=v.created_at,
        row_count=v.row_count,
        column_count=v.column_count,
        configuration=v.configuration,
        job=job_json(j) if j else None,
    )


class DatasetInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class CompareInput(BaseModel):
    baseline_id: str = Field(max_length=36)
    candidate_id: str = Field(max_length=36)


@app.get("/api/health")
def health():
    with Session() as s:
        s.execute(select(1))
    return {"status": "ok"}


@app.post("/api/datasets", status_code=201)
def create_dataset(body: DatasetInput):
    if not body.name.strip():
        raise APIError(422, "invalid_name", "Enter a dataset name.")
    with Session.begin() as s:
        d = Dataset(name=body.name.strip())
        s.add(d)
        s.flush()
        return {"id": d.id, "name": d.name, "created_at": d.created_at}


@app.get("/api/datasets")
def datasets(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    with Session() as s:
        output = []
        for d in s.scalars(
            select(Dataset)
            .order_by(Dataset.created_at.desc())
            .offset(offset)
            .limit(limit)
        ):
            versions = list(
                s.scalars(
                    select(Version)
                    .where(Version.dataset_id == d.id)
                    .order_by(Version.created_at.desc())
                )
            )
            j = (
                s.scalar(select(Job).where(Job.version_id == versions[0].id))
                if versions
                else None
            )
            output.append(
                {
                    "id": d.id,
                    "name": d.name,
                    "created_at": d.created_at,
                    "version_count": len(versions),
                    "latest_upload": versions[0].created_at if versions else None,
                    "status": j.status if j else "empty",
                }
            )
        return {
            "items": output,
            "offset": offset,
            "limit": limit,
            "total": s.scalar(select(func.count()).select_from(Dataset)),
        }


@app.get("/api/datasets/{id}")
def dataset(id: str):
    with Session() as s:
        d = require(s, Dataset, id)
        vs = list(
            s.scalars(
                select(Version)
                .where(Version.dataset_id == id)
                .order_by(Version.created_at)
            )
        )
        return {
            "id": d.id,
            "name": d.name,
            "created_at": d.created_at,
            "versions": [
                version_json(v, s.scalar(select(Job).where(Job.version_id == v.id)))
                for v in vs
            ],
        }


@app.post("/api/datasets/{id}/versions", status_code=202)
async def upload(
    id: str,
    request: Request,
    filename: str = Query("upload.csv", min_length=1, max_length=255),
    missing_tokens: str = Query("[]", max_length=2048),
):
    try:
        tokens = json.loads(missing_tokens)
        if (
            not isinstance(tokens, list)
            or len(tokens) > 30
            or any(not isinstance(t, str) or len(t) > 100 for t in tokens)
        ):
            raise ValueError()
        config = Config(missing_tokens=tuple(tokens))
    except (ValueError, TypeError):
        raise APIError(
            422,
            "invalid_options",
            "Missing tokens must be a JSON list of at most 30 strings.",
        )
    with Session() as s:
        require(s, Dataset, id)
    STORAGE.mkdir(parents=True, exist_ok=True)
    key = str(uuid4()) + ".csv"
    path = STORAGE / key
    size = 0
    digest = hashlib.sha256()
    committed = False
    try:
        with path.open("xb") as dest:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise APIError(
                        413, "file_too_large", "Maximum file size is 25 MiB."
                    )
                dest.write(chunk)
                digest.update(chunk)
        await asyncio.to_thread(parse_csv, path)
        with Session.begin() as s:
            # Same parent lock as deletion: no upload/deletion race.
            d = s.scalar(select(Dataset).where(Dataset.id == id).with_for_update())
            if not d:
                raise APIError(404, "not_found", "Dataset no longer exists.")
            v = Version(
                dataset_id=id,
                filename=Path(filename).name,
                storage_key=key,
                sha256=digest.hexdigest(),
                size=size,
                configuration=config.to_dict(),
            )
            s.add(v)
            s.flush()
            j = Job(dataset_id=id, version_id=v.id, kind="profile")
            s.add(j)
            s.flush()
            result = {"version_id": v.id, "job_id": j.id}
        committed = True
        return result
    except InputError as exc:
        raise APIError(422, "invalid_csv", str(exc))
    finally:
        if not committed:
            path.unlink(missing_ok=True)


@app.get("/api/versions/{id}")
def version(id: str):
    with Session() as s:
        return version_json(
            require(s, Version, id), s.scalar(select(Job).where(Job.version_id == id))
        )


def completed(s, id):
    require(s, Version, id)
    a = s.scalar(select(Analysis).where(Analysis.version_id == id))
    if a is None:
        j = s.scalar(select(Job).where(Job.version_id == id))
        raise APIError(
            409,
            "analysis_unavailable",
            "Analysis is not complete.",
            {"status": j.status if j else "unknown"},
        )
    return a


@app.get("/api/versions/{id}/analysis")
def analysis(id: str):
    with Session() as s:
        a = completed(s, id)
        result = load_analysis(s, id)
        fs = list(s.scalars(select(Finding).where(Finding.analysis_id == a.id)))
        result["finding_counts"] = dict(Counter(f.severity for f in fs))
        result["category_counts"] = dict(Counter(f.check_id for f in fs))
        return result


@app.get("/api/versions/{id}/findings")
def findings(
    id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
):
    with Session() as s:
        a = completed(s, id)
        q = select(Finding).where(Finding.analysis_id == a.id)
        fs = list(
            s.scalars(
                q.order_by(Finding.check_id, Finding.column_name, Finding.id)
                .offset(offset)
                .limit(limit)
            )
        )
        total = s.scalar(
            select(func.count()).select_from(Finding).where(Finding.analysis_id == a.id)
        )
        return {
            "items": [dict(id=f.id, **f.result) for f in fs],
            "total": total,
            "offset": offset,
            "limit": limit,
        }


@app.get("/api/jobs/{id}")
def job(id: str):
    with Session() as s:
        return job_json(require(s, Job, id))


@app.post("/api/comparisons", status_code=202)
def create_comparison(body: CompareInput):
    with Session.begin() as s:
        a = require(s, Version, body.baseline_id)
        b = require(s, Version, body.candidate_id)
        if a.dataset_id != b.dataset_id or a.id == b.id:
            raise APIError(
                422,
                "invalid_comparison",
                "Choose two different versions of the same dataset.",
            )
        d = s.scalar(
            select(Dataset).where(Dataset.id == a.dataset_id).with_for_update()
        )
        if not d:
            raise APIError(404, "not_found", "Dataset no longer exists.")
        completed(s, a.id)
        completed(s, b.id)
        c = Comparison(dataset_id=a.dataset_id, baseline_id=a.id, candidate_id=b.id)
        s.add(c)
        s.flush()
        j = Job(dataset_id=a.dataset_id, comparison_id=c.id, kind="compare")
        s.add(j)
        s.flush()
        return {"comparison_id": c.id, "job_id": j.id}


@app.get("/api/comparisons/{id}")
def comparison(id: str):
    with Session() as s:
        c = require(s, Comparison, id)
        j = s.scalar(select(Job).where(Job.comparison_id == id))
        return {
            "id": c.id,
            "baseline_id": c.baseline_id,
            "candidate_id": c.candidate_id,
            "result": c.result,
            "job": job_json(j),
        }


@app.get("/api/versions/{id}/report.json")
def report(id: str, include_examples: bool = False):
    with Session() as s:
        a = completed(s, id)
        v = require(s, Version, id)
        result = deepcopy(load_analysis(s, id))
        result["metadata"] = {
            "dataset": require(s, Dataset, v.dataset_id).name,
            "filename": v.filename,
            "sha256": v.sha256,
            "size": v.size,
            "version_id": id,
        }
        result["findings"] = [
            deepcopy(f.result)
            for f in s.scalars(select(Finding).where(Finding.analysis_id == a.id))
        ]
        if not include_examples:
            for c in result["columns"]:
                c.pop("examples", None)
                c["stats"].pop("top_values", None)
            for f in result["findings"]:
                f.pop("examples", None)
        result["examples_included"] = include_examples
        return JSONResponse(
            result,
            headers={
                "Content-Disposition": f'attachment; filename="datalens-{id}.json"'
            },
        )


@app.delete("/api/datasets/{id}", status_code=204)
def remove_dataset(id: str):
    with Session.begin() as s:
        d = s.scalar(select(Dataset).where(Dataset.id == id).with_for_update())
        if not d:
            raise APIError(404, "not_found", "Dataset does not exist.")
        if s.scalar(
            select(Job.id)
            .where(Job.dataset_id == id, Job.status.in_(["queued", "running"]))
            .limit(1)
        ):
            raise APIError(
                409,
                "active_jobs",
                "Wait for queued or running jobs to finish before deleting this dataset.",
            )
        for v in s.scalars(select(Version).where(Version.dataset_id == id)):
            s.add(Cleanup(storage_key=v.storage_key))
        s.delete(d)
    try:
        cleanup_files()
    except OSError:
        pass  # Worker retries durable cleanup records.
    return Response(status_code=204)
