"""Set TEST_DATABASE_URL to an EMPTY, disposable PostgreSQL database."""

import importlib
import os
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import create_engine, select, func, update
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app.models import Base, Job, Analysis, now


@pytest.fixture
def system(tmp_path, monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "TEST_DATABASE_URL not set: PostgreSQL integration requires a disposable database."
        )
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql", (
        "Integration tests require PostgreSQL, not SQLite."
    )
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = sessionmaker(engine, expire_on_commit=False)
    main = importlib.import_module("app.main")
    worker = importlib.import_module("app.worker")
    for mod in (main, worker):
        monkeypatch.setattr(mod, "Session", session)
        monkeypatch.setattr(mod, "STORAGE", tmp_path)
    with TestClient(main.app) as client:
        yield client, worker, session, tmp_path
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.mark.postgres
def test_full_journey(system):
    client, w, Session, storage = system
    d = client.post("/api/datasets", json={"name": "Test"}).json()["id"]
    u = client.post(
        f"/api/datasets/{d}/versions?filename=first.csv", content="a,b\n1,x\n1,x\n2,y\n"
    )
    assert u.status_code == 202
    v = u.json()["version_id"]
    j = u.json()["job_id"]
    assert client.get(f"/api/versions/{v}/analysis").status_code == 409
    assert client.delete(f"/api/datasets/{d}").status_code == 409
    assert w.run_once()
    assert client.get(f"/api/jobs/{j}").json()["status"] == "completed"
    assert (
        client.get(f"/api/versions/{v}/analysis").json()["summary"][
            "duplicate_rows_beyond_first"
        ]
        == 1
    )
    fs = client.get(f"/api/versions/{v}/findings?limit=1").json()
    assert len(fs["items"]) == 1
    assert fs["total"] >= 1
    report = client.get(f"/api/versions/{v}/report.json").json()
    assert all(
        "examples" not in c and "top_values" not in c["stats"]
        for c in report["columns"]
    )
    v2 = client.post(
        f"/api/datasets/{d}/versions?filename=next.csv", content="a,c\n3,z\n4,z\n"
    ).json()["version_id"]
    w.run_once()
    c = client.post(
        "/api/comparisons", json={"baseline_id": v, "candidate_id": v2}
    ).json()["comparison_id"]
    w.run_once()
    r = client.get(f"/api/comparisons/{c}").json()["result"]
    assert r["added_columns"] == ["c"]
    # A new attempt replaces results; does not multiply them.
    with Session.begin() as s:
        s.execute(update(Job).where(Job.id == j).values(status="queued"))
    w.run_once()
    with Session() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Analysis)
                .where(Analysis.version_id == v)
            )
            == 1
        )
    assert client.delete(f"/api/datasets/{d}").status_code == 204
    assert not list(storage.iterdir())
    assert client.get(f"/api/versions/{v}").status_code == 404


@pytest.mark.postgres
def test_invalid_upload_and_limits(system):
    client, w, Session, storage = system
    d = client.post("/api/datasets", json={"name": "Test"}).json()["id"]
    r = client.post(f"/api/datasets/{d}/versions", content="a,a\n1,2\n")
    assert r.status_code == 422 and r.json()["code"] == "invalid_csv"
    assert r.json()["request_id"] != "unknown"
    assert not list(storage.iterdir())
    r = client.post(
        f"/api/datasets/{d}/versions", content=b"x" * (25 * 1024 * 1024 + 1)
    )
    assert r.status_code == 413
    assert not list(storage.iterdir())
    assert client.get("/api/datasets?limit=999").status_code == 422


@pytest.mark.postgres
def test_claim_fencing_and_recovery(system):
    client, w, Session, storage = system
    d = client.post("/api/datasets", json={"name": "Test"}).json()["id"]
    client.post(f"/api/datasets/{d}/versions", content="x\n1\n").raise_for_status()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: w.claim(), range(2)))
    assert sum(c is not None for c in claims) == 1
    old = next(c for c in claims if c)
    with Session.begin() as s:
        s.get(Job, old[0]).lease_until = now() - timedelta(seconds=1)
    new = w.claim()
    assert new[0] == old[0] and new[1] != old[1]
    w.process(*old)
    assert client.get(f"/api/jobs/{old[0]}").json()["status"] == "running"
    w.process(*new)
    assert client.get(f"/api/jobs/{old[0]}").json()["status"] == "completed"


@pytest.mark.postgres
def test_transient_failures_are_bounded(system, monkeypatch):
    client, w, Session, storage = system
    d = client.post("/api/datasets", json={"name": "Test"}).json()["id"]
    u = client.post(f"/api/datasets/{d}/versions", content="x\n1\n").json()

    def fail(*args, **kwargs):
        raise RuntimeError("secret source value must never be returned")

    monkeypatch.setattr(w, "profile", fail)
    for _ in range(3):
        w.run_once()
    j = client.get(f"/api/jobs/{u['job_id']}").json()
    assert j["status"] == "failed" and j["attempts"] == 3
    assert "secret" not in j["error_message"]
    assert not w.run_once()
