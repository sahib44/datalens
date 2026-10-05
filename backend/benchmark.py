"""Fresh-process benchmark; macOS ru_maxrss is bytes, Linux is KiB."""

import csv, json, platform, resource, sys, tempfile, time
from pathlib import Path
from app.profiling import parse_csv, profile

n = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "benchmark.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "amount", "region", "date", "channel"])
        for i in range(n):
            w.writerow(
                [
                    f"{i:08d}",
                    f"{20 + i % 997 / 10:.2f}",
                    ["North", "South", "West"][i % 3],
                    "2025-01-01",
                    "Online",
                ]
            )
    start = time.perf_counter()
    h, rows = parse_csv(p)
    parsed = time.perf_counter()
    r = profile(h, rows)
    end = time.perf_counter()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(
        json.dumps(
            {
                "os": platform.platform(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "rows": n,
                "columns": 5,
                "bytes": p.stat().st_size,
                "parse_seconds": round(parsed - start, 4),
                "profile_seconds": round(end - parsed, 4),
                "total_seconds": round(end - start, 4),
                "peak_rss_mib": round(
                    rss / (1024**2 if sys.platform == "darwin" else 1024), 2
                ),
                "memory_method": "process lifetime peak resident set size from resource.getrusage; includes imports",
                "scope": "single process parse + profile only; excludes upload, DB, queue and rendering",
            }
        )
    )
