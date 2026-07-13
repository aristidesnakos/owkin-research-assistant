"""Data access: the CSV, loaded once, with gene symbols canonicalized at load.

Canonicalizing here rather than at each call site means every lookup in the application is keyed
on gene identity rather than on whichever spelling happened to reach the file.

That merge can collide -- two rows of one cohort that were distinct strings and are now one gene --
and the loader raises rather than keeping a row. Choosing between two scientific values by file
order is exactly the choice this system exists not to make. (This CSV: zero collisions.)
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

import pandas as pd

import genes

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "owkin_take_home_data.csv")


class DatasetError(RuntimeError):
    """The CSV on disk violates an invariant the rest of the application relies on."""


@lru_cache(maxsize=1)
def load_frame() -> pd.DataFrame:
    """Columns: cancer_indication, gene (HGNC-approved), gene_as_recorded, median_value."""
    # Resolved per call rather than at import: a path frozen at module scope is read before the
    # entry point's load_dotenv() has run, which is what made OWKIN_DATA_PATH dead config.
    df = pd.read_csv(os.environ.get("OWKIN_DATA_PATH") or _DEFAULT_PATH)
    df["cancer_indication"] = df["cancer_indication"].astype(str).str.strip().str.lower()
    df["gene_as_recorded"] = df["gene"].astype(str).str.strip()
    df["gene"] = df["gene_as_recorded"].map(genes.canonical)

    collisions = df[df.duplicated(subset=["cancer_indication", "gene"], keep=False)]
    if not collisions.empty:
        pairs = ", ".join(
            f"{r.cancer_indication}/{r.gene} (recorded as {r.gene_as_recorded}={r.median_value})"
            for r in collisions.sort_values(["cancer_indication", "gene"]).itertuples()
        )
        raise DatasetError(
            f"the same gene is recorded twice in one cohort under two identifiers: {pairs}. "
            "Picking one by file order would be an arbitrary scientific choice; resolve the "
            "source data instead."
        )
    return df


def available_indications() -> List[str]:
    """The cancer cohorts this dataset holds rows for."""
    return sorted(load_frame()["cancer_indication"].unique().tolist())


def available_genes() -> List[str]:
    """The HGNC-approved gene symbols this dataset holds rows for."""
    return sorted(load_frame()["gene"].unique().tolist())
