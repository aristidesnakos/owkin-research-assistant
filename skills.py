"""The skills the model may call. Every number in every answer is computed here, in pandas.

The model routes; this module computes. That split is the product's one guarantee, and it used to
leak in a way worth naming, because the fix shapes every function below.

**An empty container was the universal sentinel.** `get_targets` returned a bare `[]` and
`get_expressions` a bare `{}`, and between them those encoded five different conditions: the cohort
is absent; the cohort is present but the phrasing missed it; the gene is absent; the gene is
present under another identifier (HER2/ERBB2); the caller passed a bare string, so `list("TP53")`
became `['T','P','5','3']` and matched nothing. The prompt then told the model to read emptiness as
fact. Every bug therefore converted into a confident false statement with a clean audit trail --
the trace panel laundered the error.

So no skill returns a bare container. Every gene asked for comes back in `values` or in
`not_found`; every cohort term comes back with a `status`. And `get_expressions` requires a cohort,
because picking one of TP53's eight rows on the caller's behalf is a scientific selection, and
selection is computation.

There is no across-gene aggregate skill, and that absence is deliberate -- see AGGREGATE_NOTE.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

import genes
import indications
from data import available_genes, available_indications, load_frame

# Attached to every result carrying a number. The unit governs what may be said about the values,
# and it is the one thing the dataset never records.
UNIT_NOTE = (
    "The unit of median_value is not recorded anywhere in this dataset -- it is not TPM, FPKM, a "
    "z-score or a percentile, or if it is, nothing says so. Values can be reported, and compared "
    "for the same gene across cohorts, but no claim about 'high' or 'low' expression is supported, "
    "and two different genes are not on a known common scale."
)

# Why there is no aggregation function, authored here rather than improvised by the model. The
# headline question -- "the median expression of genes involved in breast cancer" -- reads as a
# request for one number, and one number is not available.
AGGREGATE_NOTE = (
    "There is no single median across these genes, and this tool will not compute one. A median is "
    "an order statistic, not an average: the median of a pool cannot be recovered from the medians "
    "of its groups. Doing it properly needs a sample size and a spread per gene, and this dataset "
    "records neither -- and it would still be asking what the typical value is across genes that "
    "measure different things. The per-gene table below is the answer to the question."
)


def _requested(symbols: Sequence[str] | str) -> List[str]:
    """Guard the caller's list. A bare string is one gene, not four: `list('TP53')` is
    `['T','P','5','3']`, which matches nothing and reports a real gene as absent."""
    if isinstance(symbols, str):
        symbols = [symbols]
    return [str(s).strip() for s in symbols if str(s).strip()]


def _canonicalize(symbols: Sequence[str] | str) -> tuple[List[str], List[Dict[str, str]]]:
    """De-duplicate by gene identity rather than by spelling: ['HER2', 'ERBB2'] is one gene asked
    for twice. Returns the approved symbols, plus the rewrites the reader is owed."""
    approved: List[str] = []
    rewrites: List[Dict[str, str]] = []
    for raw in _requested(symbols):
        symbol = genes.canonical(raw)
        if symbol in approved:
            continue
        approved.append(symbol)
        rewrite = genes.rewrite_of(raw)
        if rewrite:
            rewrites.append(rewrite)
    return approved, rewrites


def _unknown_indication(cancer_name: str) -> Dict[str, Any]:
    """The refusal, on the tool's authority rather than the model's judgement, with the
    alternatives attached so the model never has to invent what "no rows" means."""
    return {
        "status": "unknown_indication",
        "cancer": str(cancer_name).strip(),
        "available": available_indications(),
    }


def get_targets(cancer_name: str) -> Dict[str, Any]:
    """The genes this dataset holds rows for in one cancer cohort.

    Note the framing, which is not pedantry: these are the genes *present in this file* for this
    cohort -- not the genes "involved in" the disease, and not validated drug targets ("target"
    asserts druggability the file does not establish). A gene's absence here is evidence about the
    file, not about the biology.
    """
    cohort = indications.resolve(cancer_name)
    if cohort is None:
        return {**_unknown_indication(cancer_name), "genes": [], "resolved": []}

    rows = load_frame().query("cancer_indication == @cohort")
    return {
        "status": "ok",
        "cancer": cohort,
        # Ordered, de-duplicated, canonical -- so this output is a valid get_expressions input.
        "genes": list(dict.fromkeys(rows["gene"].tolist())),
        "resolved": [r for r in (genes.rewrite_of(g) for g in rows["gene_as_recorded"]) if r],
        "available": available_indications(),
    }


def get_expressions(genes_requested: Sequence[str] | str, cancer_name: str) -> Dict[str, Any]:
    """The recorded median value of each gene, within one cohort.

    `cancer_name` is required, and that is the whole point: TP53 is 0.233 in breast and 0.071 in
    gastric, so a gene alone has no median value to report. The old signature made it optional and
    then resolved the ambiguity by keeping the first matching row -- that is, by CSV file order.
    pandas still did the arithmetic, so the guarantee held for computation and failed for
    selection. For a question that names no cohort, use `get_gene_profile`.
    """
    approved, rewrites = _canonicalize(genes_requested)
    cohort = indications.resolve(cancer_name)
    if cohort is None:
        return {
            **_unknown_indication(cancer_name),
            "values": {},
            "not_found": approved,
            "resolved": rewrites,
            "note": UNIT_NOTE,
        }

    rows = load_frame().query("cancer_indication == @cohort")
    recorded = dict(zip(rows["gene"], rows["median_value"]))

    values = {g: float(recorded[g]) for g in approved if g in recorded}
    result: Dict[str, Any] = {
        "status": "ok",
        "cancer": cohort,
        "values": values,
        # Absence is stated, never implied by omission. `not_found` means this file holds no row
        # for the gene -- NOT that the gene is unrecognised, and NOT that it is uninvolved in the
        # disease. EGFR lands here for lung, and EGFR is among the most consequential targets in
        # lung cancer. That is a fact about the file.
        "not_found": [g for g in approved if g not in recorded],
        "resolved": rewrites,
        "note": UNIT_NOTE,
    }
    if len(values) > 1:
        result["aggregate_note"] = AGGREGATE_NOTE
    return result


def get_gene_profile(genes_requested: Sequence[str] | str) -> Dict[str, Any]:
    """Every (cancer, median_value) pair this dataset holds for a gene.

    The answer when a question names a gene but no cohort. It structurally cannot collapse to a
    scalar: TP53 spans 0.071 to 0.972 across eight cohorts, and any single number picked from them
    would have been picked by row order. There is no correct scalar answer to "the median of TP53";
    the question is malformed, and handing back all eight pairs is the honest reply.
    """
    approved, rewrites = _canonicalize(genes_requested)
    df = load_frame()

    profiles: Dict[str, List[Dict[str, Any]]] = {}
    not_found: List[str] = []
    for symbol in approved:
        rows = df.query("gene == @symbol").sort_values("cancer_indication")
        if rows.empty:
            not_found.append(symbol)
            continue
        profiles[symbol] = [
            {"cancer": r.cancer_indication, "median_value": float(r.median_value)}
            for r in rows.itertuples()
        ]

    return {
        "status": "ok",
        "profiles": profiles,
        "not_found": not_found,
        "resolved": rewrites,
        "note": UNIT_NOTE,
    }


def describe_capabilities() -> Dict[str, Any]:
    """What this assistant can and cannot answer, authored in code.

    "How can you help me?" is the one question a model answers from memory, and a model asked what
    a biostatistics tool does will cheerfully offer differential expression and survival analysis.
    The softest question in the suite is where the biggest overclaim lands. A product's
    self-description is a claim like any other, so it is computed from the dataset and written
    here.
    """
    df = load_frame()
    return {
        "status": "ok",
        "dataset": (
            f"One table: the median value recorded for a (gene, cancer) pair. {len(df)} rows, "
            f"{len(available_indications())} cancers, {len(available_genes())} genes. "
            "No sample size, no spread, no unit, and no healthy-tissue baseline."
        ),
        "i_can": [
            "List the genes this dataset holds for a cancer.",
            "Report the recorded median value of a gene within one cancer.",
            "Show one gene's recorded values across every cancer it appears in.",
            "Resolve a gene's aliases to its approved symbol (HER2 is ERBB2) and tell you I did.",
            "Tell you when a cancer or a gene is not in this dataset, instead of guessing.",
        ],
        "i_cannot": [
            "Give a single overall value across genes: a median of medians is not an expression "
            "level, so no such number exists here.",
            "Say whether a value is high or low, or compare one gene against another: the unit is "
            "not recorded, so the genes are not on a known common scale and there is no baseline.",
            "Test anything for significance -- no p-value, confidence interval or effect size. "
            "Sample size and spread are not recorded, so none of it is computable.",
            "Answer anything needing per-sample data: this is one median per (gene, cancer), not "
            "an expression matrix, and there are no clinical outcomes here.",
            "Tell you whether a patient or tumour is HER2-positive: that is a clinical status, and "
            "this is a gene-level median.",
            "Tell you a gene is not involved in a cancer. I can only say this file holds no row "
            "for it -- and the file is not a map of the biology.",
        ],
        "indications": available_indications(),
        "note": UNIT_NOTE,
    }
