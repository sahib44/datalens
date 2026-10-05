# Build and understand DataLens

Read this beside the code. Python handles the analysis; React manages what you see; SQL preserves work across browser refreshes and process restarts.

## Milestone 1: one complete journey

**Acceptance:** upload valid CSV → receive job ID → worker processes it → browser displays the saved summary. Malformed input produces an actionable error.

An HTTP request is the browser asking the server to do something. Upload uses POST with CSV bytes. The server checks the size as bytes arrive, then validates the file. It stores metadata and a job in a database transaction: both are saved together, or neither is. HTTP 202 means “accepted for processing,” not “finished.”

The worker is a separate Python process. It takes queued jobs and computes results. React polls for updates: it asks the API periodically instead of holding the original upload request open.

Main code:
- `backend/app/main.py`: HTTP routes, validation and resource lifecycle.
- `backend/app/models.py`: relational entities and constraints.
- `backend/app/worker.py`: job claiming, computation and persistence.
- `frontend/src/main.tsx`: browser forms, selection, polling and display.
- `backend/migrations/versions/0001_initial.py`: explicit database schema creation.

A migration is a version-controlled change to the database schema. SQLAlchemy maps Python objects to tables; Alembic applies schema changes. A foreign key says a child record must refer to an existing parent. A unique constraint prevents duplicate identities, such as two current analyses for the same version.

**Tradeoff:** validation parses the CSV before queueing, then the worker reads it again. This adds work but returns malformed-input errors immediately and keeps the worker input immutable.

**Exercise:** trace the returned `job_id` from the upload route to the React polling logic. Explain why completing the upload is different from completing the analysis.

**Interview explanation:** “The upload API stores an immutable file and queues a durable job. A separate worker writes results atomically, and the frontend polls for completion.”

## Milestone 2: evidence, not automatic cleanup

**Acceptance:** all six check categories expose explanations, denominators, bounded evidence, rules and limitations; hand-computed tests verify results.

`backend/app/profiling.py` contains no API or database code. Its `profile()` function takes a parsed table and configuration and returns ordinary Python dictionaries. This makes the logic easy to test independently.

Missingness is a fraction with an explicit denominator. Twenty missing records in a 200-row column means 10% missing; the overall missing-cell fraction divides by rows × columns. Blank and whitespace-only values are missing by default. “NA” is retained unless configured as a token.

Type inference uses boolean words, finite numbers, then ISO dates, falling back to text. A 95% numeric parse rate allows a mostly numeric column to retain a few invalid values as evidence. That is an inference, not a business contract. Leading-zero values such as 00123 stay text.

Outliers use IQR = Q3 − Q1. Fences are Q1 − 1.5 × IQR and Q3 + 1.5 × IQR. For [1,2,3,4,100], Q1=2, Q3=4, and the upper fence is 7. The value 100 is flagged; it is not removed. With zero IQR or fewer than four finite values, the check is skipped and explained.

Duplicates use exact decoded strings without trimming or case normalization. Three equal rows mean two duplicates beyond the first and three members in a duplicate group. These are different counts.

Formatting checks group case/whitespace variants for review. A constant column can be valid metadata; a nearly unique column might be an identifier or a continuous measurement. These get informational findings.

**Tradeoff:** conservative rules are explainable and testable but do not establish domain correctness. There is no universal quality score.

**Exercise:** change the configured missingness warning threshold in a unit test. Predict how severity changes without changing the missing count.

**Interview explanation:** “Each check returns its rule, affected count, denominator, original record examples, limitations and next action, so users can verify the finding.”

## Milestone 3: comparing versions

**Acceptance:** two completed versions can be compared by exact column name, with schema changes, missingness deltas and aligned distributions. Reports export complete findings.

`backend/app/comparison.py` implements descriptive comparisons. A missing rate changing from 10% to 25% is +15 percentage points, not +15 percent. Row-count and distinct-count differences are simple deltas.

Numeric histograms use the same bin edges in both versions. The Kolmogorov–Smirnov statistic measures the largest gap between empirical cumulative distributions. A value of 0 means matching empirical distributions; 1 means complete separation. This app does not turn a p-value into a quality verdict.

Categorical total variation distance is half the sum of absolute frequency differences. [A:100%,B:0%] versus [A:0%,B:100%] has distance 1. The top 20 pooled categories are retained, with remaining categories grouped as Other. Rare changes can be hidden by aggregation; the interface discloses this.

No stable key means no record-level diff. A renamed column is listed as removed and added. Different configured missing tokens can themselves change apparent missingness.

**Tradeoff:** bounded comparisons stay readable and manageable, at the cost of losing detail about rare categories.

**Exercise:** manually compute total variation for [A:75%,B:25%] versus [A:25%,B:75%]. Expected answer: 0.5.

**Interview explanation:** “I separate changes in data from claims about quality. Distribution changes are descriptive evidence and do not prove reduced model accuracy.”

## Milestone 4: reliability and presentation

**Acceptance:** tests exercise real PostgreSQL, concurrent claims, retries, idempotent persistence, cleanup and a complete browser workflow. The README records verification limits honestly.

`SELECT … FOR UPDATE SKIP LOCKED` locks a queued job while a worker claims it. Other workers skip that row. A lease expires if a worker stops renewing it. A new claim receives a different token, which acts as a fence: an old worker cannot save results after losing ownership.

This is at-least-once processing. Work can be performed again after a crash. Idempotent persistence means repeated attempts do not multiply saved analyses. The unique constraint and atomic replacement transaction enforce that property.

Deletion takes the dataset lock and refuses active jobs. It commits durable cleanup records with metadata deletion. The worker retries file deletion if immediate removal fails. Files are retained until deletion; this local version has no automatic retention schedule.

**Tradeoff:** the database doubles as the job queue, which reduces setup burden. At much higher volume a dedicated queue might become useful, but it would not automatically remove the need for idempotency.

**Exercise:** read `test_claim_fencing_and_recovery`. Identify why the stale token must be checked when saving, not just when starting.

**Interview explanation:** “I tested competing worker claims and expired-lease recovery against PostgreSQL, and used claim tokens plus transactional writes to stop stale workers from publishing results.” Use this sentence only after that test has passed in your environment; see VERIFICATION.md.

## React concepts to learn next

- `useState`: the component remembers the selected dataset, version and input values.
- `useEffect`: starts external work such as fetching data; cleanup prevents outdated requests from changing the current screen.
- Props: values passed into smaller display components such as a finding card or histogram.
- Controlled inputs: React state is the source of truth for a text box or selector.
- Rendering: a state update causes React to compute the next interface. It does not re-run the backend analysis.

Useful improvement after understanding the first version: split the main React module into feature components and typed API hooks. Preserve behavior with the end-to-end test while refactoring.
