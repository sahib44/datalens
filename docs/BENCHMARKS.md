# Profiling benchmark

Measured September 16, 2026. macOS 26.5.2, ARM64, Python 3.12.14, NumPy 2.5.3. Each measurement ran in a fresh Python process with one workload and no concurrent benchmark workers. This is one run per size, not a latency distribution or a service-level promise.

| Rows | Columns | CSV bytes | Parse seconds | Profile seconds | Total seconds | Peak RSS MiB |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 5 | 39,895 | 0.0053 | 0.0302 | 0.0355 | 31.98 |
| 10,000 | 5 | 398,668 | 0.0596 | 0.1562 | 0.2158 | 40.22 |
| 100,000 | 5 | 3,986,398 | 0.3309 | 1.0578 | 1.3887 | 126.53 |

Scope: strict parsing and in-memory profiling. Excludes upload, API validation's additional parse, database writes, queue delay and frontend rendering. Peak memory uses process-lifetime `resource.getrusage().ru_maxrss` and includes Python imports. macOS reports bytes; the script converts to MiB. Linux reports KiB and is converted accordingly.

Reproduce from `backend/` in the project virtual environment:

```sh
python benchmark.py 1000
python benchmark.py 10000
python benchmark.py 100000
```

The generator uses deterministic five-column synthetic records; it is not representative of all real datasets. Wider files, long strings, high cardinality, concurrent jobs and different hardware can use more time and memory. The 100-column ceiling was not performance-benchmarked in these measurements. Input boundaries are tested separately; maximum limits are product constraints, not capacity claims.
