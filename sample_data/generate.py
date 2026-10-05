"""Deterministic synthetic retail data. No real customers or businesses."""

import csv
from datetime import date, timedelta
from pathlib import Path
import random


def generate(directory=None, n=200):
    root = Path(directory or Path(__file__).parent)
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    header = ["order_id", "order_date", "region", "amount", "channel", "note"]
    rows = [
        [
            f"{i + 1:06d}",
            str(date(2025, 1, 1) + timedelta(days=i % 60)),
            rng.choice(["North", "South", "West"]),
            f"{rng.uniform(20, 180):.2f}",
            "Online",
            rng.choice(["Gift", "Standard"]),
        ]
        for i in range(n)
    ]

    def write(name, h, data):
        with (root / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(h)
            w.writerows(data)

    write("retail_clean.csv", header, rows)
    messy = [r[:] for r in rows]
    for i in range(0, n, 10):
        messy[i][2] = ""
    messy[1][3] = "unknown"
    messy[2][3] = "9999.00"
    messy[3][2] = " north "
    messy[4][2] = "NORTH"
    messy.extend([messy[5][:], messy[5][:], messy[6][:]])
    write("retail_messy.csv", header, messy)
    changed = [r[:-1] + ["repeat" if i % 3 else "new"] for i, r in enumerate(rows)]
    for i, r in enumerate(changed):
        r[3] = f"{float(r[3]) * 1.8:.2f}"
        if i % 4 == 0:
            r[2] = ""
    write("retail_next.csv", header[:-1] + ["customer_segment"], changed)
    return root


if __name__ == "__main__":
    generate()
