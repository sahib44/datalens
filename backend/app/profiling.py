"""Pure, versioned CSV parsing and profiling. No HTTP or database dependencies."""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
import csv
import math
from pathlib import Path
import re
import numpy as np

ENGINE_VERSION = "1.0.0"
MAX_BYTES = 25 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 100


class InputError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    missing_tokens: tuple = ()
    dominant_threshold: float = 0.95
    missing_warning: float = 0.10
    missing_high: float = 0.50
    near_constant: float = 0.95
    identifier_threshold: float = 0.98
    example_limit: int = 5

    def __post_init__(self):
        for value in (
            self.dominant_threshold,
            self.missing_warning,
            self.missing_high,
            self.near_constant,
            self.identifier_threshold,
        ):
            if not 0 < value <= 1:
                raise InputError(
                    "Thresholds must be greater than zero and at most one."
                )
        if self.missing_warning > self.missing_high:
            raise InputError(
                "Missing warning threshold must not exceed high threshold."
            )
        if not 1 <= self.example_limit <= 10:
            raise InputError("Example limit must be between 1 and 10.")

    def missing(self, value):
        return not value.strip() or value.strip() in self.missing_tokens

    def to_dict(self):
        return asdict(self)


def parse_csv(path, max_rows=MAX_ROWS, max_columns=MAX_COLUMNS):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise InputError("File exceeds the 25 MiB limit.")
    # Reject bare quotes in unquoted fields: csv.reader(strict=True) alone permits them.
    state = "start"
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for chunk in iter(lambda: stream.read(65536), ""):
                for ch in chunk:
                    if ch == "\x00":
                        raise InputError("NUL characters are not supported.")
                    if state == "quoted":
                        if ch == '"':
                            state = "closed"
                    elif state == "closed":
                        if ch == '"':
                            state = "quoted"
                        elif ch in ",\r\n":
                            state = "start"
                        else:
                            raise InputError(
                                "Unexpected character after a quoted field."
                            )
                    elif state == "start":
                        if ch == '"':
                            state = "quoted"
                        elif ch not in ",\r\n":
                            state = "plain"
                    else:
                        if ch == '"':
                            raise InputError("Quote inside an unquoted field.")
                        if ch in ",\r\n":
                            state = "start"
            if state == "quoted":
                raise InputError("Unclosed quoted field.")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            csv.field_size_limit(MAX_BYTES)
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            if not header:
                raise InputError("The file is empty or has no header.")
            if len(header) > max_columns:
                raise InputError(f"Maximum {max_columns} columns exceeded.")
            if any(not name.strip() for name in header):
                raise InputError("Column names must not be empty.")
            if len(set(header)) != len(header):
                raise InputError("Duplicate column names are not supported.")
            rows = []
            for number, row in enumerate(reader, 1):
                if number > max_rows:
                    raise InputError(f"Maximum {max_rows:,} data records exceeded.")
                if len(row) != len(header):
                    raise InputError(
                        f"Data record {number} has {len(row)} fields; expected {len(header)}."
                    )
                rows.append(row)
            return header, rows
    except UnicodeDecodeError as exc:
        raise InputError("Use UTF-8 encoding (a UTF-8 BOM is supported).") from exc
    except csv.Error as exc:
        raise InputError(f"Malformed CSV: {exc}") from exc


def numeric(value):
    v = value.strip()
    if re.match(r"^[+-]?0\d", v):
        return None  # Preserve leading-zero identifiers.
    try:
        number = float(v)
        return number if math.isfinite(number) else None
    except (ValueError, OverflowError):
        return None


def boolean(value):
    v = value.strip().casefold()
    return v == "true" if v in ("true", "false") else None


def date_value(value):
    v = value.strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|T| )", v):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def infer(values, config):
    if not values:
        return "empty", 0.0, []
    # Boolean words first, finite numbers second, ISO dates third. Text is fallback.
    for kind, parser in [
        ("boolean", boolean),
        ("numeric", numeric),
        ("datetime", date_value),
    ]:
        parsed = [parser(v) for v in values]
        rate = sum(v is not None for v in parsed) / len(values)
        if rate >= config.dominant_threshold:
            return kind, rate, parsed
    return "text", 1.0, list(values)


def bounded(value):
    return value[:120] + ("…" if len(value) > 120 else "")


def profile(header, rows, config=None):
    config = config or Config()
    n = len(rows)
    findings, columns = [], []
    missing_total = 0

    def add(
        check,
        column,
        count,
        denominator,
        explanation,
        rule,
        limitation,
        next_step,
        examples=(),
        severity="info",
    ):
        findings.append(
            dict(
                check_id=check,
                check_version=1,
                column=column,
                severity=severity,
                count=count,
                denominator=denominator,
                rate=count / denominator if denominator else None,
                explanation=explanation,
                rule=rule,
                limitation=limitation,
                next_step=next_step,
                examples=list(examples)[: config.example_limit],
            )
        )

    for position, name in enumerate(header):
        raw = [row[position] for row in rows]
        present = [(i + 1, v) for i, v in enumerate(raw) if not config.missing(v)]
        values = [v for _, v in present]
        missing = n - len(values)
        missing_total += missing
        counts = Counter(values)
        kind, rate, parsed = infer(values, config)
        stats, warnings = {}, []
        examples = [
            {"record": i, "value": bounded(v)}
            for i, v in present[: config.example_limit]
        ]
        col = dict(
            position=position,
            name=name,
            type=kind,
            parse_rate=rate,
            missing_count=missing,
            missing_rate=missing / n if n else None,
            distinct_count=len(counts),
            nonmissing_count=len(values),
            examples=examples,
            stats=stats,
            warnings=warnings,
        )
        if missing:
            severity = (
                "high"
                if missing / n >= config.missing_high
                else "warning"
                if missing / n >= config.missing_warning
                else "info"
            )
            add(
                "missing",
                name,
                missing,
                n,
                f"{missing} of {n} records are missing a value.",
                {
                    "warning_rate": config.missing_warning,
                    "high_rate": config.missing_high,
                    "tokens": list(config.missing_tokens),
                },
                "Missing values may be intentional; thresholds are project defaults, not universal rules.",
                "Check whether this field is required and whether missingness follows a pattern.",
                (
                    {"record": i + 1, "value": bounded(v)}
                    for i, v in enumerate(raw)
                    if config.missing(v)
                ),
                severity,
            )
        if kind in ("numeric", "boolean", "datetime"):
            failures = [
                {"record": i, "value": bounded(v)}
                for (i, v), p in zip(present, parsed)
                if p is None
            ]
            if failures:
                add(
                    "parse_failure",
                    name,
                    len(failures),
                    len(values),
                    f"Some nonmissing values do not parse as {kind}.",
                    {
                        "dominant_threshold": config.dominant_threshold,
                        "supporting_rate": rate,
                    },
                    "Inference does not establish a business schema. Alternate formats can be legitimate.",
                    "Inspect failed values and confirm the intended column type.",
                    failures,
                    "warning",
                )
        if kind == "numeric":
            array = np.array([v for v in parsed if v is not None], dtype=float)
            with np.errstate(over="ignore", invalid="ignore"):
                q1, median, q3 = np.quantile(array, [0.25, 0.5, 0.75])
                mean, sd = np.mean(array), np.std(array, ddof=0)
                lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
                stats.update(
                    min=float(array.min()),
                    max=float(array.max()),
                    mean=float(mean),
                    median=float(median),
                    std_population=float(sd),
                    q1=float(q1),
                    q3=float(q3),
                    finite_count=len(array),
                )
                try:
                    hist, edges = np.histogram(
                        array, bins=min(12, max(1, len(set(array))))
                    )
                    stats["histogram"] = {
                        "counts": hist.tolist(),
                        "edges": edges.tolist(),
                    }
                except (ValueError, IndexError, OverflowError):
                    warnings.append(
                        "Histogram omitted because the numeric range is too extreme."
                    )
            if len(array) < 4 or q3 == q1:
                warnings.append(
                    "IQR outlier check skipped: fewer than four finite values or zero IQR."
                )
            elif math.isfinite(lo) and math.isfinite(hi):
                out = [
                    {"record": i, "value": bounded(v)}
                    for (i, v), p in zip(present, parsed)
                    if p is not None and (p < lo or p > hi)
                ]
                if out:
                    add(
                        "outlier",
                        name,
                        len(out),
                        len(array),
                        "Values lie beyond the 1.5 × IQR fences.",
                        {
                            "q1": float(q1),
                            "q3": float(q3),
                            "iqr": float(q3 - q1),
                            "lower": float(lo),
                            "upper": float(hi),
                        },
                        "Potential outliers can be valid observations; this rule assumes no business context.",
                        "Inspect these records before deciding whether any correction is justified.",
                        out,
                        "warning",
                    )
        elif kind == "datetime":
            good = [v for v in parsed if v is not None]
            zones = {str(v.tzinfo) for v in good}
            if len(zones) > 1:
                warnings.append(
                    "Mixed timezone conventions: earliest/latest are omitted."
                )
            else:
                stats.update(
                    earliest=min(good).isoformat(), latest=max(good).isoformat()
                )
            warnings.append(
                "Only ISO year-month-day formats are parsed; timezone-free values retain local/unspecified time."
            )
        elif kind == "boolean":
            stats.update(
                true_count=sum(v is True for v in parsed),
                false_count=sum(v is False for v in parsed),
            )
        elif values:
            lengths = [len(v) for v in values]
            stats.update(
                min_length=min(lengths),
                median_length=float(np.median(lengths)),
                max_length=max(lengths),
            )
            if any(
                re.match(r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}$", v.strip())
                for v in values
            ):
                warnings.append(
                    "Date-like values use an ambiguous or unsupported format; retained as text."
                )
        stats["top_values"] = [
            {"value": bounded(v), "count": c}
            for v, c in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:10]
        ]
        if values:
            groups = defaultdict(Counter)
            for v in values:
                groups[" ".join(v.split()).casefold()][v] += 1
            variants = [g for g in groups.values() if len(g) > 1]
            if variants:
                affected = sum(sum(g.values()) for g in variants)
                add(
                    "formatting",
                    name,
                    affected,
                    len(values),
                    "Some values differ only in case or whitespace.",
                    {"normalization": "strip, collapse whitespace, Unicode casefold"},
                    "Case or spacing may carry meaning. Source data has not been changed.",
                    "Review each group before standardizing categories.",
                    (
                        {
                            "variants": [
                                {"value": bounded(v), "count": c}
                                for v, c in g.most_common(5)
                            ]
                        }
                        for g in variants
                    ),
                )
            most = counts.most_common(1)[0][1]
            if most / len(values) >= config.near_constant:
                add(
                    "low_information",
                    name,
                    most,
                    len(values),
                    "Column is constant or nearly constant among nonmissing values.",
                    {"near_constant_threshold": config.near_constant},
                    "A constant value can be valid metadata.",
                    "Check whether this field adds useful information for your analysis.",
                    examples,
                )
            if (
                len(values) >= 20
                and len(counts) / len(values) >= config.identifier_threshold
            ):
                add(
                    "identifier_like",
                    name,
                    len(counts),
                    len(values),
                    "Most nonmissing values are distinct; this may be an identifier.",
                    {
                        "distinct_fraction_threshold": config.identifier_threshold,
                        "minimum_nonmissing": 20,
                    },
                    "Continuous measurements can also be unique. Uniqueness is not a defect.",
                    "Confirm whether the column is a key before using it as a model feature.",
                    examples,
                )
        elif n:
            add(
                "empty_column",
                name,
                n,
                n,
                "The entire column is missing.",
                {"definition": "no nonmissing records"},
                "An empty column can be reserved for future data.",
                "Confirm whether this field should be populated.",
            )
        columns.append(col)
    groups = defaultdict(list)
    for i, row in enumerate(rows, 1):
        groups[tuple(row)].append(i)
    duplicates = [ids for ids in groups.values() if len(ids) > 1]
    beyond = sum(len(ids) - 1 for ids in duplicates)
    members = sum(len(ids) for ids in duplicates)
    if beyond:
        add(
            "duplicate",
            None,
            beyond,
            n,
            "Exact duplicate records occur beyond their first occurrence.",
            {
                "normalization": "none; exact raw decoded field strings",
                "rows_in_duplicate_groups": members,
            },
            "Repeated records may represent legitimate repeated events.",
            "Check business keys or source-system semantics before removing rows.",
            ({"records": ids[:5], "group_size": len(ids)} for ids in duplicates),
            "warning",
        )
    result = dict(
        engine_version=ENGINE_VERSION,
        configuration=config.to_dict(),
        summary=dict(
            rows=n,
            columns=len(header),
            missing_cells=missing_total,
            missing_rate=missing_total / (n * len(header)) if n else None,
            duplicate_rows_beyond_first=beyond,
            rows_in_duplicate_groups=members,
        ),
        columns=columns,
        findings=findings,
        limitations=[
            "Findings are inspection prompts, not proof of errors.",
            "Record numbers are one-based data records excluding the header, not physical line numbers.",
            "Text fallback parse_rate=1 means values are representable as text, not certainty about business meaning.",
        ],
    )
    return finite_json(result)


def finite_json(value):
    """JSON has no NaN or infinity; extreme arithmetic is explicitly unavailable."""
    if isinstance(value, dict):
        return {k: finite_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_json(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
