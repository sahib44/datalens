import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Job = {
  id: string;
  status: string;
  stage: string;
  error_message: string | null;
};
type Version = {
  id: string;
  filename: string;
  size: number;
  created_at: string;
  job: Job;
  row_count: number | null;
};
type Dataset = {
  id: string;
  name: string;
  version_count: number;
  status: string;
  latest_upload: string | null;
};
type Detail = { id: string; name: string; versions: Version[] };
type Finding = {
  id: string;
  check_id: string;
  column: string | null;
  severity: string;
  count: number;
  denominator: number;
  explanation: string;
  rule: unknown;
  limitation: string;
  next_step: string;
  examples: unknown[];
};
type Column = {
  name: string;
  type: string;
  parse_rate: number;
  missing_count: number;
  missing_rate: number | null;
  distinct_count: number;
  nonmissing_count: number;
  stats: Record<string, any>;
  warnings: string[];
  examples: unknown[];
};
type Analysis = {
  engine_version: string;
  created_at: string;
  configuration: unknown;
  summary: {
    rows: number;
    columns: number;
    missing_rate: number | null;
    duplicate_rows_beyond_first: number;
    rows_in_duplicate_groups: number;
  };
  columns: Column[];
  finding_counts: Record<string, number>;
  category_counts: Record<string, number>;
  limitations: string[];
};
async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, init);
  if (!r.ok) {
    const e = await r
      .json()
      .catch(() => ({ message: `Request failed (${r.status})` }));
    throw new Error(e.message || "Request failed");
  }
  return r.status === 204 ? (undefined as T) : r.json();
}
const json = (body: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const pct = (x: number | null | undefined) =>
  x == null ? "—" : `${(x * 100).toFixed(1)}%`;
const num = (x: number | null | undefined) =>
  x == null
    ? "—"
    : Number.isInteger(x)
      ? x.toLocaleString()
      : x.toLocaleString(undefined, { maximumFractionDigits: 3 });
const label = (s: string) => s.replaceAll("_", " ");
function Badge({ text }: { text: string }) {
  return <span className={`badge ${text}`}>{label(text)}</span>;
}
function Histogram({ data }: { data: { counts: number[]; edges: number[] } }) {
  const max = Math.max(1, ...data.counts);
  return (
    <figure>
      <div
        className="histogram"
        role="img"
        aria-label={`Histogram with ${data.counts.length} bins. Counts: ${data.counts.join(", ")}`}
      >
        {data.counts.map((c, i) => (
          <div
            key={i}
            title={`${num(data.edges[i])} – ${num(data.edges[i + 1])}: ${c}`}
            style={{ height: `${Math.max(2, (c / max) * 100)}%` }}
          />
        ))}
      </div>
      <figcaption>
        {num(data.edges[0])}
        <span>Value range · bin height is record count</span>
        {num(data.edges.at(-1))}
      </figcaption>
    </figure>
  );
}
function App() {
  const fileInput = useRef<HTMLInputElement>(null);
  const [library, setLibrary] = useState<Dataset[]>([]),
    [libraryPage, setLibraryPage] = useState(0),
    [libraryTotal, setLibraryTotal] = useState(0),
    [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null),
    [version, setVersion] = useState(""),
    [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]),
    [total, setTotal] = useState(0),
    [page, setPage] = useState(0);
  const [tab, setTab] = useState("overview"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(false);
  const [name, setName] = useState(""),
    [file, setFile] = useState<File | null>(null),
    [tokens, setTokens] = useState(""),
    [search, setSearch] = useState(""),
    [column, setColumn] = useState("");
  const [baseline, setBaseline] = useState(""),
    [candidate, setCandidate] = useState(""),
    [comparison, setComparison] = useState<any>(null),
    [comparisonId, setComparisonId] = useState("");
  const [includeExamples, setIncludeExamples] = useState(false),
    [reload, setReload] = useState(0);
  const selectedVersion = detail?.versions.find((v) => v.id === version);
  async function refreshLibrary() {
    const r = await api<{ items: Dataset[]; total: number }>(
      `/datasets?offset=${libraryPage * 50}`,
    );
    setLibrary(r.items);
    setLibraryTotal(r.total);
  }
  useEffect(() => {
    refreshLibrary().catch((e) => setError(e.message));
  }, [reload, libraryPage]);
  useEffect(() => {
    setDetail(null);
    setVersion("");
    setAnalysis(null);
    setFindings([]);
    setComparison(null);
    setComparisonId("");
    setBaseline("");
    setCandidate("");
    setTab("overview");
    setPage(0);
    setColumn("");
    if (!selected) return;
    let active = true;
    api<Detail>(`/datasets/${selected}`)
      .then((d) => {
        if (active) {
          setDetail(d);
          setVersion(d.versions.at(-1)?.id || "");
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [selected]);
  useEffect(() => {
    if (
      !selected ||
      !detail?.versions.some((v) =>
        ["queued", "running"].includes(v.job.status),
      )
    )
      return;
    let active = true;
    const timer = setInterval(async () => {
      try {
        const d = await api<Detail>(`/datasets/${selected}`);
        if (active) {
          setDetail(d);
          setReload((x) => x + 1);
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    }, 1200);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [selected, detail]);
  useEffect(() => {
    setPage(0);
    setColumn("");
    setAnalysis(null);
    setFindings([]);
  }, [version]);
  useEffect(() => {
    if (!version || selectedVersion?.job.status !== "completed") return;
    let active = true;
    setLoading(true);
    Promise.all([
      api<Analysis>(`/versions/${version}/analysis`),
      api<{ items: Finding[]; total: number }>(
        `/versions/${version}/findings?offset=${page * 50}`,
      ),
    ])
      .then(([a, f]) => {
        if (active) {
          setAnalysis(a);
          setFindings(f.items);
          setTotal(f.total);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [version, selectedVersion?.job.status, page]);
  useEffect(() => {
    if (!comparisonId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const c = await api<any>(`/comparisons/${comparisonId}`);
        if (!active) return;
        setComparison(c);
        if (["queued", "running"].includes(c.job.status))
          timer = setTimeout(poll, 1200);
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    };
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [comparisonId]);
  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      if (file.size > 25 * 1024 * 1024)
        throw new Error("Maximum file size is 25 MiB.");
      const id =
        selected || (await api<{ id: string }>("/datasets", json({ name }))).id;
      const options = new URLSearchParams({
        filename: file.name,
        missing_tokens: JSON.stringify(
          tokens
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        ),
      });
      const r = await api<{ version_id: string }>(
        `/datasets/${id}/versions?${options}`,
        { method: "POST", headers: { "Content-Type": "text/csv" }, body: file },
      );
      if (id !== selected) setSelected(id);
      else {
        setDetail(await api<Detail>(`/datasets/${id}`));
        setVersion(r.version_id);
      }
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setName("");
      setTab("overview");
      setReload((x) => x + 1);
    } catch (e) {
      setError((e as Error).message);
      setReload((x) => x + 1);
    } finally {
      setBusy(false);
    }
  }
  async function runComparison() {
    setBusy(true);
    setError("");
    try {
      const r = await api<{ comparison_id: string }>(
        "/comparisons",
        json({ baseline_id: baseline, candidate_id: candidate }),
      );
      setComparison(null);
      setComparisonId(r.comparison_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (
      !selected ||
      !window.confirm(
        "Delete this dataset, every version, and its stored files?",
      )
    )
      return;
    setBusy(true);
    try {
      await api(`/datasets/${selected}`, { method: "DELETE" });
      setSelected("");
      setReload((x) => x + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const inspected = analysis?.columns.find((c) => c.name === column);
  return (
    <div className="app">
      <aside className="sidebar no-print">
        <a className="brand" href="/">
          ▧ <span>DataLens</span>
        </a>
        <p className="eyebrow">YOUR WORKSPACE</p>
        <button
          className={!selected ? "nav active" : "nav"}
          disabled={busy}
          onClick={() => {
            setSelected("");
            setError("");
          }}
        >
          ＋ New dataset
        </button>
        <div className="library-title">
          DATASET LIBRARY <span>{libraryTotal}</span>
        </div>
        {library.map((d) => (
          <button
            key={d.id}
            disabled={busy}
            className={`dataset-link ${selected === d.id ? "active" : ""}`}
            onClick={() => {
              setSelected(d.id);
              setError("");
            }}
          >
            <strong>{d.name}</strong>
            <span>
              {d.version_count} versions · {d.status}
            </span>
            {d.latest_upload && (
              <small>{new Date(d.latest_upload).toLocaleDateString()}</small>
            )}
          </button>
        ))}
        {libraryTotal > 50 && (
          <div className="pagination">
            <button
              disabled={!libraryPage}
              onClick={() => setLibraryPage((p) => p - 1)}
            >
              Previous
            </button>
            <button
              disabled={(libraryPage + 1) * 50 >= libraryTotal}
              onClick={() => setLibraryPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        )}
        <div className="sidebar-note">
          LOCAL WORKSPACE
          <br />
          <span>Files stay on this server until you delete the dataset.</span>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <p className="eyebrow">DATASET QUALITY INSPECTOR</p>
            <h1>{detail?.name || "Know what’s in your data."}</h1>
            <p className="muted">
              {detail
                ? "Inspect the evidence. Understand what changed."
                : "Find missing values, inconsistencies, and unexpected changes in your CSV files."}
            </p>
          </div>
          {selected && (
            <button
              className="subtle no-print"
              disabled={busy}
              onClick={remove}
            >
              Delete dataset
            </button>
          )}
        </header>
        {error && (
          <div role="alert" className="error no-print">
            {error}
            <button onClick={() => setError("")} aria-label="Dismiss error">
              ×
            </button>
          </div>
        )}
        <section className="upload-panel no-print">
          <div>
            <p className="eyebrow">
              {selected ? "ADD A VERSION" : "START AN INSPECTION"}
            </p>
            <h2>
              {selected ? "Compare your next upload." : "Upload your dataset."}
            </h2>
            <p className="muted">
              CSV · UTF-8 · up to 25 MiB
              <br />
              100,000 rows · 100 columns
            </p>
          </div>
          <form onSubmit={upload}>
            {!selected && (
              <label>
                Dataset name
                <input
                  required
                  maxLength={120}
                  placeholder="e.g. Retail orders"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
            )}
            <label className="file-field">
              CSV file
              <input
                ref={fileInput}
                required
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            </label>
            <label>
              Extra missing-value tokens{" "}
              <span className="muted">(optional, comma separated)</span>
              <input
                value={tokens}
                onChange={(e) => setTokens(e.target.value)}
                placeholder="e.g. NULL, N/A"
              />
            </label>
            <button className="primary" disabled={busy || !file}>
              {busy ? "Working…" : "Upload & inspect"}
            </button>
          </form>
        </section>
        {!selected && (
          <section className="empty">
            <span className="big-mark">▤</span>
            <h2>A clear view, before the analysis.</h2>
            <p>
              Upload a file to see its structure, inspect quality findings, and
              establish a baseline for future versions.
            </p>
            <div className="feature-row">
              <span>01 &nbsp; Profile columns</span>
              <span>02 &nbsp; Inspect evidence</span>
              <span>03 &nbsp; Compare versions</span>
            </div>
            <p className="muted">
              No automatic edits. Findings are prompts to investigate—not proof
              of errors.
            </p>
          </section>
        )}
        {detail && detail.versions.length > 0 && (
          <>
            <div className="toolbar no-print">
              <label>
                Version
                <select
                  value={version}
                  disabled={busy}
                  onChange={(e) => setVersion(e.target.value)}
                >
                  {detail.versions.map((v, i) => (
                    <option key={v.id} value={v.id}>
                      v{i + 1} · {v.filename} · {v.job.status}
                    </option>
                  ))}
                </select>
              </label>
              <div className="tabs" role="tablist" aria-label="Dataset views">
                {["overview", "findings", "compare", "report"].map((t) => (
                  <button
                    role="tab"
                    disabled={busy}
                    aria-selected={tab === t}
                    key={t}
                    className={tab === t ? "active" : ""}
                    onClick={() => setTab(t)}
                  >
                    {t[0].toUpperCase() + t.slice(1)}
                  </button>
                ))}
              </div>
            </div>
            {selectedVersion && selectedVersion.job.status !== "completed" && (
              <div className="status" role="status">
                <Badge text={selectedVersion.job.status} />
                <h2>
                  {selectedVersion.job.status === "failed"
                    ? "Analysis could not finish"
                    : `Processing: ${selectedVersion.job.stage}`}
                </h2>
                <p>
                  {selectedVersion.job.error_message ||
                    "The worker is inspecting your file. This page updates automatically."}
                </p>
                {selectedVersion.job.status === "failed" && (
                  <p>Inspect the error, then upload a corrected version.</p>
                )}
              </div>
            )}
            {loading && <p role="status">Loading analysis…</p>}
            {analysis && (
              <>
                {tab === "overview" && (
                  <>
                    <div className="metrics">
                      <Metric
                        title="Data records"
                        value={num(analysis.summary.rows)}
                      />
                      <Metric
                        title="Columns"
                        value={num(analysis.summary.columns)}
                      />
                      <Metric
                        title="Missing cells"
                        value={pct(analysis.summary.missing_rate)}
                      />
                      <Metric
                        title="Duplicates beyond first"
                        value={num(
                          analysis.summary.duplicate_rows_beyond_first,
                        )}
                      />
                    </div>
                    <p className="muted">
                      {num(analysis.summary.rows_in_duplicate_groups)} records
                      belong to duplicate groups ·{" "}
                      {num((selectedVersion?.size || 0) / 1024)} KiB · Analyzed{" "}
                      {new Date(analysis.created_at).toLocaleString()}
                    </p>
                    <section className="panel">
                      <div className="section-head">
                        <div>
                          <p className="eyebrow">AT A GLANCE</p>
                          <h2>Column profiles</h2>
                        </div>
                        <label>
                          Search columns
                          <input
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Column name"
                          />
                        </label>
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Column</th>
                              <th>Inferred type</th>
                              <th>Parse support</th>
                              <th>Missing</th>
                              <th>Distinct</th>
                            </tr>
                          </thead>
                          <tbody>
                            {analysis.columns
                              .filter((c) =>
                                c.name
                                  .toLowerCase()
                                  .includes(search.toLowerCase()),
                              )
                              .map((c) => (
                                <tr key={c.name}>
                                  <td>
                                    <button
                                      className="link"
                                      onClick={() => setColumn(c.name)}
                                    >
                                      {c.name}
                                    </button>
                                  </td>
                                  <td>
                                    <Badge text={c.type} />
                                  </td>
                                  <td>{pct(c.parse_rate)}</td>
                                  <td>{pct(c.missing_rate)}</td>
                                  <td>{num(c.distinct_count)}</td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                    </section>
                    {inspected && (
                      <section className="panel column-detail">
                        <div className="section-head">
                          <div>
                            <p className="eyebrow">COLUMN DETAIL</p>
                            <h2>{inspected.name}</h2>
                          </div>
                          <button onClick={() => setColumn("")}>Close</button>
                        </div>
                        <p>
                          {inspected.type} · {pct(inspected.parse_rate)} parse
                          support · {num(inspected.nonmissing_count)} nonmissing
                          records
                        </p>
                        <dl className="stats">
                          {Object.entries(inspected.stats)
                            .filter(
                              ([k, v]) =>
                                k !== "histogram" &&
                                k !== "top_values" &&
                                typeof v !== "object",
                            )
                            .map(([k, v]) => (
                              <div key={k}>
                                <dt>{label(k)}</dt>
                                <dd>
                                  {typeof v === "number" ? num(v) : String(v)}
                                </dd>
                              </div>
                            ))}
                        </dl>
                        {inspected.stats.histogram && (
                          <Histogram data={inspected.stats.histogram} />
                        )}
                        {inspected.stats.top_values?.length > 0 && (
                          <>
                            <h3>Most frequent values</h3>
                            <ul>
                              {inspected.stats.top_values.map(
                                (v: any, i: number) => (
                                  <li key={i}>
                                    <code>{v.value}</code> — {num(v.count)}{" "}
                                    records
                                  </li>
                                ),
                              )}
                            </ul>
                          </>
                        )}
                        {inspected.warnings.map((w) => (
                          <p className="notice" key={w}>
                            {w}
                          </p>
                        ))}
                        <details>
                          <summary>Original examples</summary>
                          <pre>
                            {JSON.stringify(inspected.examples, null, 2)}
                          </pre>
                        </details>
                        <p>
                          Column findings are listed in the Findings tab with
                          their column names and record evidence.
                        </p>
                      </section>
                    )}
                    <section className="panel">
                      <h2>Findings by category</h2>
                      <div className="feature-row">
                        {Object.entries(analysis.category_counts).map(
                          ([k, v]) => (
                            <span key={k}>
                              {label(k)} <strong>{v}</strong>
                            </span>
                          ),
                        )}
                      </div>
                      {!Object.keys(analysis.category_counts).length && (
                        <p>No configured checks produced findings.</p>
                      )}
                      <p className="muted">
                        A finding is a reason to investigate. It does not mean a
                        record should be removed.
                      </p>
                    </section>
                  </>
                )}
                {tab === "findings" && (
                  <section>
                    <div className="section-head">
                      <h2>
                        Inspection findings{" "}
                        <span className="muted">({total})</span>
                      </h2>
                      <div>
                        {Object.entries(analysis.finding_counts).map(
                          ([s, n]) => (
                            <span key={s} className="count">
                              <Badge text={s} /> {n}
                            </span>
                          ),
                        )}
                      </div>
                    </div>
                    {findings.map((f) => (
                      <FindingCard key={f.id} finding={f} />
                    ))}
                    {!total && (
                      <p className="empty">
                        No findings under the configured rules.
                      </p>
                    )}
                    <div className="pagination">
                      <button
                        disabled={page === 0}
                        onClick={() => setPage((p) => p - 1)}
                      >
                        Previous
                      </button>
                      <span>
                        {total ? page * 50 + 1 : 0}–
                        {Math.min(total, (page + 1) * 50)} of {total}
                      </span>
                      <button
                        disabled={(page + 1) * 50 >= total}
                        onClick={() => setPage((p) => p + 1)}
                      >
                        Next
                      </button>
                    </div>
                  </section>
                )}
                {tab === "compare" && (
                  <section className="panel">
                    <p className="eyebrow">VERSION COMPARISON</p>
                    <h2>What changed?</h2>
                    <p className="muted">
                      Choose two completed versions. Columns match by exact
                      name.
                    </p>
                    <div className="compare-controls">
                      <label>
                        Baseline
                        <select
                          value={baseline}
                          onChange={(e) => setBaseline(e.target.value)}
                        >
                          <option value="">Choose version</option>
                          {detail.versions
                            .filter((v) => v.job.status === "completed")
                            .map((v) => (
                              <option key={v.id} value={v.id}>
                                {v.filename} · {v.id.slice(0, 6)}
                              </option>
                            ))}
                        </select>
                      </label>
                      <label>
                        Candidate
                        <select
                          value={candidate}
                          onChange={(e) => setCandidate(e.target.value)}
                        >
                          <option value="">Choose version</option>
                          {detail.versions
                            .filter((v) => v.job.status === "completed")
                            .map((v) => (
                              <option key={v.id} value={v.id}>
                                {v.filename} · {v.id.slice(0, 6)}
                              </option>
                            ))}
                        </select>
                      </label>
                      <button
                        className="primary"
                        disabled={
                          busy ||
                          !baseline ||
                          !candidate ||
                          baseline === candidate
                        }
                        onClick={runComparison}
                      >
                        Compare versions
                      </button>
                    </div>
                    {comparison && !comparison.result && (
                      <p role="status">
                        {comparison.job.stage} {comparison.job.error_message}
                      </p>
                    )}
                    {comparison?.result && (
                      <ComparisonView result={comparison.result} />
                    )}
                  </section>
                )}
                {tab === "report" && (
                  <Report
                    version={version}
                    analysis={analysis}
                    name={detail.name}
                    filename={selectedVersion?.filename || ""}
                    includeExamples={includeExamples}
                    onExamples={setIncludeExamples}
                  />
                )}
              </>
            )}
          </>
        )}
        <footer>
          DataLens <span>Evidence before assumptions.</span>
        </footer>
      </main>
    </div>
  );
}
function Metric({ title, value }: { title: string; value: string }) {
  return (
    <div className="metric">
      <span>{title}</span>
      <strong>{value}</strong>
    </div>
  );
}
function FindingCard({
  finding: f,
  examples = true,
  expanded = false,
}: {
  finding: Finding;
  examples?: boolean;
  expanded?: boolean;
}) {
  return (
    <article className="finding">
      <div className="section-head">
        <div>
          <Badge text={f.severity} />
          <span className="finding-type">{label(f.check_id)}</span>
        </div>
        <code>{f.column || "Entire dataset"}</code>
      </div>
      <h3>{f.explanation}</h3>
      <p>
        {f.count.toLocaleString()} / {f.denominator.toLocaleString()} ·{" "}
        {pct(f.denominator ? f.count / f.denominator : null)}
      </p>
      <p className="muted">{f.limitation}</p>
      <p>
        <strong>Next step:</strong> {f.next_step}
      </p>
      <details open={expanded}>
        <summary>Rule{examples ? " & evidence" : ""}</summary>
        <pre>{JSON.stringify(f.rule, null, 2)}</pre>
        {examples && <pre>{JSON.stringify(f.examples, null, 2)}</pre>}
      </details>
    </article>
  );
}
function ComparisonView({ result: r }: { result: any }) {
  return (
    <div className="comparison-result">
      <div className="metrics">
        <Metric title="Baseline records" value={num(r.baseline_rows)} />
        <Metric title="Candidate records" value={num(r.candidate_rows)} />
        <Metric title="Record change" value={num(r.row_count_change)} />
      </div>
      <p>
        <strong>Added columns:</strong> {r.added_columns.join(", ") || "None"}
      </p>
      <p>
        <strong>Removed columns:</strong>{" "}
        {r.removed_columns.join(", ") || "None"}
      </p>
      {r.warnings.map((w: string) => (
        <p className="notice" key={w}>
          {w}
        </p>
      ))}
      {r.columns.map((c: any) => (
        <article className="comparison-column" key={c.name}>
          <h3>{c.name}</h3>
          <p>
            {c.baseline_type} → {c.candidate_type} · Missingness change:{" "}
            {num(c.missingness_delta_pp)} percentage points · Distinct count
            change: {num(c.distinct_count_change)}
          </p>
          {c.numeric && (
            <>
              <p>
                Finite samples: {num(c.numeric.baseline_finite)} →{" "}
                {num(c.numeric.candidate_finite)} · KS distance:{" "}
                {num(c.numeric.ks_statistic)}
              </p>
              <div className="two-col">
                {c.numeric.histogram &&
                  ["baseline", "candidate"].map((k) => (
                    <div key={k}>
                      <h4>{k}</h4>
                      <Histogram
                        data={{
                          counts: c.numeric.histogram[k],
                          edges: c.numeric.histogram.edges,
                        }}
                      />
                    </div>
                  ))}
              </div>
              <p>
                Mean: {num(c.numeric.baseline_summary.mean)} →{" "}
                {num(c.numeric.candidate_summary.mean)} · Median:{" "}
                {num(c.numeric.baseline_summary.median)} →{" "}
                {num(c.numeric.candidate_summary.median)}
              </p>
            </>
          )}
          {c.categorical && (
            <>
              <p>
                Total variation distance: {num(c.categorical.total_variation)}{" "}
                (0 = identical, 1 = no overlap)
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th>Baseline share</th>
                      <th>Candidate share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.categorical.categories.map(
                      (v: string | null, i: number) => (
                        <tr key={i}>
                          <td>{v === null ? "Other (aggregated)" : v}</td>
                          <td>{pct(c.categorical.baseline[i])}</td>
                          <td>{pct(c.categorical.candidate[i])}</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {c.warnings.map((w: string) => (
            <p className="muted" key={w}>
              {w}
            </p>
          ))}
        </article>
      ))}
    </div>
  );
}
function Report({
  version,
  analysis: a,
  name,
  filename,
  includeExamples,
  onExamples,
}: {
  version: string;
  analysis: Analysis;
  name: string;
  filename: string;
  includeExamples: boolean;
  onExamples: (v: boolean) => void;
}) {
  const [fs, setFs] = useState<Finding[]>([]),
    [error, setError] = useState(""),
    [ready, setReady] = useState(false);
  useEffect(() => {
    let active = true;
    setReady(false);
    setError("");
    (async () => {
      const all: Finding[] = [];
      let offset = 0;
      while (true) {
        const r = await api<{ items: Finding[]; total: number }>(
          `/versions/${version}/findings?offset=${offset}&limit=100`,
        );
        all.push(...r.items);
        offset += r.items.length;
        if (offset >= r.total) break;
      }
      if (active) {
        setFs(all);
        setReady(true);
      }
    })().catch((e) => {
      if (active) setError(e.message);
    });
    return () => {
      active = false;
    };
  }, [version]);
  return (
    <section className="panel report">
      <div className="section-head no-print">
        <h2>Portable report</h2>
        <div className="actions">
          <a
            className="button"
            href={`/api/versions/${version}/report.json?include_examples=${includeExamples}`}
          >
            Download JSON
          </a>
          <button disabled={!ready} onClick={() => window.print()}>
            Print / save PDF
          </button>
        </div>
      </div>
      <label className="checkbox no-print">
        <input
          type="checkbox"
          checked={includeExamples}
          onChange={(e) => onExamples(e.target.checked)}
        />
        Include raw example values
      </label>
      <p className="muted no-print">
        Column names, metadata, ranges and configured tokens remain in reports.
        Review before sharing.
      </p>
      {error && <p role="alert">{error}</p>}
      {!ready && !error && <p role="status">Preparing complete report…</p>}
      <h2>
        {name} · {filename}
      </h2>
      <p>
        {a.summary.rows.toLocaleString()} records · {a.summary.columns} columns
        · {pct(a.summary.missing_rate)} missing cells
      </p>
      <p>
        Duplicate rows beyond first: {a.summary.duplicate_rows_beyond_first};
        rows in duplicate groups: {a.summary.rows_in_duplicate_groups}.
      </p>
      <p>
        Engine {a.engine_version} · {new Date(a.created_at).toLocaleString()}
      </p>
      <h3>Column summary</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Column</th>
              <th>Type</th>
              <th>Missing</th>
              <th>Distinct</th>
            </tr>
          </thead>
          <tbody>
            {a.columns.map((c) => (
              <tr key={c.name}>
                <td>{c.name}</td>
                <td>{c.type}</td>
                <td>{pct(c.missing_rate)}</td>
                <td>{c.distinct_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Configuration</h3>
      <pre>{JSON.stringify(a.configuration, null, 2)}</pre>
      {a.limitations.map((l) => (
        <p key={l}>{l}</p>
      ))}
      <h3>Findings ({fs.length})</h3>
      {fs.map((f) => (
        <FindingCard key={f.id} finding={f} examples={includeExamples} expanded />
      ))}
    </section>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
