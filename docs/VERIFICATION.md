# Verification record

Date: September 16, 2026. Local-only development; no cloud services, paid APIs, or public deployment.

## Completed checks

- Docker Compose built and started PostgreSQL 17, FastAPI, the separate worker, and the production React/nginx frontend.
- Alembic applied the explicit initial migration. `alembic check` reported no new upgrade operations.
- 24 backend tests passed against real PostgreSQL on the host Python environment (2.97 seconds).
- The same 24 tests passed inside the application Docker image against a disposable PostgreSQL test database (0.98 seconds).
- React TypeScript checking and Vite production build passed inside Docker.
- Ruff's Python undefined-name/unused-import checks passed.
- Profiling benchmarks ran in fresh processes at 1,000, 10,000 and 100,000 rows; see BENCHMARKS.md.

Backend coverage includes strict CSV errors and limits, UTF-8/BOM and quoted newlines, missing tokens, leading-zero IDs, numeric parse failures, hand-computed outliers, duplicate groups, date ambiguity, formatting variants, empty columns, descriptive version statistics, upload-to-analysis, report example removal, repeated processing, concurrent claims, stale-token fencing, bounded retries, active-job deletion protection and file cleanup.

The test client emitted two upstream deprecation warnings involving Starlette/httpx and AnyIO. They did not fail tests; updating test-client dependencies is a future maintenance task.

## Browser verification

The local macOS Chrome test launch was blocked by the execution environment. The Docker Playwright test runs the actual frontend, API, worker and database. Its first run found a file-input remount bug; the fix keeps the DOM input stable and clears it only after upload succeeds. The second run identified a timing race between navigation and upload completion; navigation now stays disabled during the upload, and the test waits for the selected version to show completion before inspecting its results. Accessible-role selectors resolve the nested select controls reliably.

Final Docker browser result: **1 passed in 5.7 seconds** (workflow execution: 5.2 seconds). Verified upload, numeric parse-failure finding, column detail, second-version processing, schema comparison, JSON download contents, 390px horizontal-overflow check, report visibility, print-media control hiding and screenshot, dataset deletion, and zero browser page errors. Screenshots are saved in `docs/screenshots/`.

## Practical limits

This is a tested local prototype, not a production readiness claim. No public exposure, load/concurrency capacity benchmark, accessibility audit, cross-browser matrix, or external security assessment was performed. The one-browser workflow includes a 390px viewport check; it does not establish full accessibility compliance. Five-column performance measurements do not establish worst-case capacity at the 100-column limit.
