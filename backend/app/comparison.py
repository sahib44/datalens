"""Descriptive version comparisons. No significance or model-performance claims."""

from collections import Counter
import numpy as np
from scipy.stats import ks_2samp
from .profiling import Config, numeric, finite_json


def compare(
    left_header, left_rows, right_header, right_rows, left_analysis, right_analysis
):
    left = {c["name"]: c for c in left_analysis["columns"]}
    right = {c["name"]: c for c in right_analysis["columns"]}
    lc, rc = (
        Config(**left_analysis["configuration"]),
        Config(**right_analysis["configuration"]),
    )
    output = {
        "row_count_change": len(right_rows) - len(left_rows),
        "baseline_rows": len(left_rows),
        "candidate_rows": len(right_rows),
        "added_columns": [c for c in right_header if c not in left],
        "removed_columns": [c for c in left_header if c not in right],
        "columns": [],
        "configuration": {"category_limit": 20, "histogram_bins": 12},
        "warnings": [
            "Distribution change is not proof of worse quality or reduced model accuracy.",
            "Columns match by exact name; renames appear as additions/removals. No row-level matching.",
        ],
    }
    if lc.missing_tokens != rc.missing_tokens:
        output["warnings"].append(
            "Versions use different missing-token settings; missingness comparisons may reflect configuration changes."
        )
    for name in left_header:
        if name not in right:
            continue
        a, b = left[name], right[name]
        ai, bi = left_header.index(name), right_header.index(name)
        av = [r[ai] for r in left_rows if not lc.missing(r[ai])]
        bv = [r[bi] for r in right_rows if not rc.missing(r[bi])]
        item = {
            "name": name,
            "baseline_type": a["type"],
            "candidate_type": b["type"],
            "baseline_missing_rate": a["missing_rate"],
            "candidate_missing_rate": b["missing_rate"],
            "missingness_delta_pp": 100 * (b["missing_rate"] - a["missing_rate"])
            if a["missing_rate"] is not None and b["missing_rate"] is not None
            else None,
            "distinct_count_change": b["distinct_count"] - a["distinct_count"],
            "baseline_nonmissing": len(av),
            "candidate_nonmissing": len(bv),
            "warnings": [],
        }
        if not av or not bv:
            item["warnings"].append(
                "Distribution comparison unavailable: one column has no nonmissing data."
            )
        elif a["type"] != b["type"]:
            item["warnings"].append(
                "Distribution comparison skipped because inferred types differ."
            )
        elif a["type"] == "numeric":
            an = np.array([p for v in av if (p := numeric(v)) is not None])
            bn = np.array([p for v in bv if (p := numeric(v)) is not None])
            item["numeric"] = {
                "baseline_summary": a["stats"],
                "candidate_summary": b["stats"],
                "baseline_finite": len(an),
                "candidate_finite": len(bn),
                "ks_statistic": float(ks_2samp(an, bn, method="asymp").statistic),
            }
            try:
                edges = np.histogram_bin_edges(np.concatenate([an, bn]), bins=12)
                item["numeric"]["histogram"] = {
                    "edges": edges.tolist(),
                    "baseline": np.histogram(an, bins=edges)[0].tolist(),
                    "candidate": np.histogram(bn, bins=edges)[0].tolist(),
                }
            except (ValueError, OverflowError, IndexError):
                item["warnings"].append(
                    "Histogram unavailable for extreme numeric range."
                )
            item["warnings"].append(
                "KS statistic describes maximum empirical CDF distance. Sample size, ties and sampling design affect interpretation; no p-value decision is made."
            )
        else:
            ac, bc = Counter(av), Counter(bv)
            categories = sorted(set(ac) | set(bc), key=lambda v: (-(ac[v] + bc[v]), v))[
                :20
            ]
            ap = [ac[v] / len(av) for v in categories]
            bp = [bc[v] / len(bv) for v in categories]
            ap.append(max(0.0, 1 - sum(ap)))
            bp.append(max(0.0, 1 - sum(bp)))
            item["categorical"] = {
                "categories": categories + [None],
                "baseline": ap,
                "candidate": bp,
                "total_variation": sum(abs(x - y) for x, y in zip(ap, bp)) / 2,
                "other_bucket_index": len(categories),
            }
            item["warnings"].append(
                "Top 20 pooled categories plus Other; aggregation can hide changes among rare categories. Frequencies exclude missing values."
            )
        if min(len(av), len(bv)) < 20:
            item["warnings"].append(
                "Small sample: distribution estimates may be unstable."
            )
        output["columns"].append(item)
    return finite_json(output)
