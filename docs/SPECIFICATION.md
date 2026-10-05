# DataLens specification

## Scope and architecture
Local CSV inspection for students and analysts: upload, inspect evidence, compare versions, export. No automatic cleaning, quality score, cloud storage, or authentication in this local version.

React browser → FastAPI API → private files + PostgreSQL job → separate Python worker → transactional profiles/findings → polling browser.

Dataset is the logical collection; version is an immutable upload; analysis is a versioned computation result; job tracks a processing attempt. Comparisons reference two completed versions of the same dataset. Column profiles and findings reference an analysis. Result-specific statistics are JSON; identity, relationships, and lifecycle are relational columns.

## Milestone acceptance criteria
1. A valid upload returns HTTP 202 with version/job IDs, a separate worker stores its analysis, and the browser displays counts. Malformed CSV fails clearly; no malformed records are discarded.
2. All six check categories expose counts, denominators, rules, examples, limitations and next steps. Engine tests cover hand-computed cases and parsing boundaries.
3. Selecting two versions returns schema, missingness and aligned distribution comparisons. Reports export valid JSON and print legibly. No record-level diff claims.
4. Worker recovery and deletion are tested; frontend builds; one full browser journey passes; reproducible sample generation, benchmarks and learning documentation are supplied. Unverified infrastructure is explicitly disclosed.

## Storage and jobs
Uploads use generated UUID filenames, never client paths. Input is limited to 25 MiB, 100,000 data records and 100 columns. API accepts raw CSV request bodies so its byte limit applies during ingestion, before multipart buffering. Display filename and parsing options are query parameters. Upload validation parses bounded records before queueing; worker parses again from immutable storage. All validation failures clean up the temporary file.

PostgreSQL row locks and SKIP LOCKED provide atomic job claiming. Five-minute leases and a heartbeat permit abandoned work to be retried up to three times. Each claim has a token: stale workers cannot commit after their lease has been reclaimed. Results and job completion commit in one transaction. Deletion is rejected with HTTP 409 while jobs are queued/running; failed/completed datasets can be deleted. File cleanup is staged through a durable database cleanup queue.

## API
- POST /api/datasets: JSON {"name":"Retail orders"}; 201 dataset.
- GET /api/datasets: bounded collection list.
- GET /api/datasets/{id}: dataset and version history.
- POST /api/datasets/{id}/versions?filename=orders.csv&missing_tokens=[]: raw text/csv; 202 {version_id,job_id}.
- GET /api/versions/{id}: version metadata and job.
- GET /api/versions/{id}/analysis: completed summary and column profiles; 409 if pending/failed.
- GET /api/versions/{id}/findings?offset=0&limit=50: paginated findings.
- GET /api/jobs/{id}: processing state and safe errors.
- POST /api/comparisons: JSON {baseline_id,candidate_id}; 202 {comparison_id,job_id}.
- GET /api/comparisons/{id}: status, result or failure.
- GET /api/versions/{id}/report.json?include_examples=false: portable analysis.
- DELETE /api/datasets/{id}: 204; active jobs cause 409.

Errors: {code,message,details,request_id}. Unknown IDs: 404. Bad CSV/options: 422. Oversize input: 413. Unavailable result: 409. Internal failures: safe 500.

## Failure behavior
Browser errors remain visible with a retry action; upload errors remove partial files; invalid parsing never queues work; transient worker failures retry with bounded attempts; expired leases recover; stale workers discard results; completed results appear atomically. Frontend polling is tied to selected work and cancelled on navigation. Files are retained until explicit dataset deletion. A public installation would require authentication/isolation, quotas, rate limits and retention controls.

## References checked
- https://fastapi.tiangolo.com/tutorial/request-files/
- https://docs.sqlalchemy.org/en/20/core/selectable.html
- https://vite.dev/guide/
