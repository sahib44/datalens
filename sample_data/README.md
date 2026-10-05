# Synthetic retail fixtures
Run `python sample_data/generate.py` from the project root. Seed: 42. No real personal data.

- `retail_clean.csv`: 200 rows; leading-zero identifiers, ISO dates, 3 regions, uniform generated amounts, constant Online channel. “Clean” still produces informational constant/identifier findings.
- `retail_messy.csv`: 203 rows; 20 empty regions, one invalid amount (`unknown`), one extreme amount (9999), whitespace/case variants, and 3 duplicates beyond first (5 members across 2 duplicate groups).
- `retail_next.csv`: 200 rows; 50 missing regions; amounts multiplied by 1.8; note removed, customer_segment added.

Record numbers exclude headers. “Unknown” amount is retained as original text and reported as a parse failure. No source is automatically repaired.
