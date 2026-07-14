# Data dictionary

`docs/owkin_take_home_data.csv` — 81 rows, 3 columns, one row per (indication, gene) pair.

| Column | Type | Notes |
|---|---|---|
| `cancer_indication` | string | 10 values: `breast` `colorectal` `gastric` `glioblastoma` `lung` `melanoma` `ovarian` `pancreatic` `prostate` `renal` |
| `gene` | string | 54 distinct strings — but **53 genes**: `HER2` (breast) and `ERBB2` (gastric) are one gene, HGNC:3430. `data.py` canonicalizes to the HGNC-approved symbol at load. |
| `median_value` | float | 3 decimal places, range 0.003–0.985. **No recorded unit.** |

Cohorts hold 5–10 genes each. **14** genes appear in more than one cohort — and the count is itself
a demonstration of the bug this repo exists to fix: keyed on the raw string you get **13**, because
`HER2` (breast) and `ERBB2` (gastric) look like two single-cohort genes. Canonicalize them to
HGNC:3430 and ERBB2 becomes a fourteenth gene spanning two cohorts. Keyed on the raw string, a
query for `ERBB2` in breast cancer returns no data at all — a false absence for the trastuzumab
target in the one cohort where trastuzumab is standard of care. `data.py` canonicalizes every
symbol to its HGNC-approved form at load, which is what fixes it. `TP53` appears in 8 cohorts,
where its value spans **0.071 (gastric) to 0.972 (ovarian)** — nearly the full range of the
column. A median belongs to a **(gene, indication) pair**, never to a gene alone.

## What the file does not record

This is the load-bearing section. It is why the assistant reports values but never ranks,
compares, or characterizes them.

- **No unit.** `median_value` is not documented as TPM, FPKM, a z-score, or a percentile.
- **No sample size.** No `n`, per gene or per cohort.
- **No dispersion.** No IQR, SD, or quantiles.
- **No baseline.** No normal or adjacent-tissue reference row.

Consequences, enforced in code rather than requested in a prompt:

- **No magnitude claims.** "High", "elevated", "overexpressed" each need a scale or a baseline.
  There is neither. `0.716` is not "twice" `0.358`.
- **No cross-gene comparison, and no ranking.** With no common stated scale, an ordering of these
  values is not interpretable. Tables are ordered alphabetically, never by value — the ordering of
  a table is itself a claim.
- **No inference.** No p-value, no confidence interval, no effect size: each needs `n` and
  dispersion, and neither is here.
- **No aggregate across genes.** A median of medians aggregates over *genes*, not samples. Medians
  do not compose, and the result has no biological referent. No such skill exists.
- **Cross-cohort comparison of one gene is *conditional*, not safe.** Every value in this file lies
  between **0.003 and 0.985**. Raw TPM is unbounded — real genes reach the hundreds — so whatever
  this is, it has been normalized into a bounded range, and nothing records *against what*. If the
  normalization is per-sample (TPM-like), then TP53's 0.071 in gastric and 0.972 in ovarian are two
  measurements of one thing, and comparable. If it is per-cohort (a percentile or rank within each
  cancer's own patients), they are positions in two different races and are **not** comparable. The
  dataset does not say which, so neither does the tool.

`skills.py` attaches this caveat (`UNIT_NOTE`), code-authored, to every result carrying a number.
It is reproduced below **verbatim** from `skills.UNIT_NOTE`, which remains the source of truth: if
the two ever disagree, the code is right and this file is stale.

> The unit of median_value is not recorded anywhere in this dataset -- it is not TPM, FPKM, a z-score or a percentile, or if it is, nothing says so. Values can be reported as the file records them, but no claim about 'high' or 'low' expression is supported, two different genes are not on a known common scale, and even one gene's values across cohorts are comparable only if the value was normalized the same way in every cohort -- which nothing states.

## Also undefined

**"Involved in"** — the CSV pairs a gene with a cancer but never says what the pairing *means*:
recurrently mutated, amplified, prognostic, therapeutically targeted, or hand-curated. So the
assistant says "genes this dataset records for lung cancer", never "genes that cause lung cancer".

Each cohort is one undivided group: no ER/PR/HER2 status, no NSCLC/SCLC split, no stage, no date.
And an absent row is a fact about **this file**, not about the biology.

The first question for the data's owner is what `median_value` measures. Until that is written
down, nothing built on top of it is fully trustworthy.
