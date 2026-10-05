# Demonstration and interview preparation

## Two-minute demonstration

**0:00–0:20 — The problem.** “Before analyzing a dataset, I need to know whether it contains missing values, inconsistent formats or unexpected changes. DataLens shows evidence rather than silently modifying records.” Open the local app and upload `retail_messy.csv` under “Retail orders.”

**0:20–0:45 — Inspect.** Show 203 rows and six columns. Open `amount`: one value fails numeric parsing, and 9999 lies beyond the IQR fences. Explain why an outlier is not automatically wrong. Show the leading-zero order IDs remain text.

**0:45–1:05 — Evidence.** Open Findings. Expand the duplicate rule and explain “three beyond first” versus “five members in duplicate groups.” Show a formatting group and its original values.

**1:05–1:35 — Compare.** Upload `retail_next.csv` as another version. Compare baseline and candidate. Show the new customer_segment field, removed note field, and increased region missingness. Show aligned amount histograms. Say “distribution changed,” not “model quality declined.”

**1:35–1:50 — Share.** Download JSON without raw examples. Show the configuration and engine version that make results reproducible. Explain that metadata and aggregates still need review before sharing.

**1:50–2:00 — Engineering.** “The API queues durable PostgreSQL jobs. A separate worker uses leases and claim tokens to recover from failure without letting stale attempts overwrite results.”

Prepare both versions ahead of a live interview if you need to eliminate processing delays. Label them as synthetic demonstrations.

## Resume bullet drafts

Use these only after you have worked through the code and can explain it. Do not imply real users or business outcomes.

- Built DataLens, a React/TypeScript and FastAPI application for CSV quality inspection, with six check categories, record-level evidence, dataset version comparison, and portable report export.
- Implemented a PostgreSQL-backed processing worker with atomic job claims, bounded retries, expiring leases, and claim-token fencing to prevent stale result writes.
- Benchmarked strict parsing and profiling of a synthetic 100,000-row, five-column CSV at 1.39 seconds and approximately 127 MiB peak process memory on an ARM64 Mac; validated statistical rules using hand-computed test cases.

The benchmark excludes HTTP upload, queue delay and database writes. Keep that qualification available when discussing the number. Replace it if later measurements use different code or hardware.

## Interview questions and answer notes

**Why use PostgreSQL as a queue?** The app already needs durable metadata. Row locking is sufficient for this scope and avoids running another service. A dedicated queue would become worth considering with greater throughput, scheduling complexity or operational needs.

**Does the worker provide exactly-once execution?** No. It provides retryable processing with idempotent result persistence. A crash can cause computation to repeat. Fencing and transactions ensure only the current claim publishes a completed result.

**Why preserve strings during CSV parsing?** Automatic coercion can erase leading zeros, reinterpret missing-value tokens, or hide malformed records. Raw values make evidence trustworthy; typed values are derived separately.

**How did you test the statistical logic?** With small hand-computed inputs: duplicate groups, explicit IQR fences, completely separated numeric distributions, and categorical total variation examples. Integration and browser checks test different boundaries.

**Why not produce an overall quality score?** Different tasks have different requirements. An identifier is good for joins but often unsuitable as a predictive feature. An arbitrary score would collapse those distinctions without domain knowledge.

**What does KS measure here?** The largest absolute difference between two empirical cumulative distributions. The app uses it descriptively; it does not claim statistical significance or causality.

**What happens if deletion races with upload?** Both lock the dataset row during their final database change. Deletion refuses queued/running jobs. File removal is tracked durably so failed cleanup can be retried.

**What would you change before public hosting?** Add user identity and access isolation, quotas, abuse controls, retention, monitoring, backup policy and deployment configuration. Start a public demo with supplied synthetic data rather than unrestricted uploads.

**What is a limitation you deliberately accepted?** The engine processes bounded files in memory, comparisons match columns by exact name, and high-cardinality categories use a disclosed top-category aggregation. These keep the first release understandable and testable.

## A decision worth explaining deeply

The raw-versus-typed representation is central. If an order ID is “00123,” converting it to 123 silently changes data. DataLens keeps the original string and derives numeric/date values separately. Findings can therefore point back to exactly what was uploaded. The cost is additional memory and explicit parsing code, but it preserves information and makes the application's claims auditable.
