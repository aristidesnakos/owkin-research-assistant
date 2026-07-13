"""Gene symbol resolution.

A symbol is a display label, not an identifier. This dataset proves it: it records one gene --
HGNC:3430 -- as `HER2` in breast and `ERBB2` in gastric. Keyed on the raw string those are two
genes, so a question about the trastuzumab target in breast cancer came back "no data for ERBB2",
which is false, and false about one of the most-asked-about targets in oncology.

Both sides of every lookup are canonicalized here: the caller's words and the CSV's. A rewrite is
never silent -- `rewrite_of` hands back what we changed, and the answer says so, because the user
asked about one symbol and is reading an answer about another.

Scope: 12 entries, covering this file's one collision plus the legacy spellings a biologist
actually types. Production resolves against HGNC's full set (~43k) and joins on hgnc_id; vendoring
that here to disambiguate 54 symbols would be the wrong trade.
"""
from __future__ import annotations

import re
from typing import Dict, Optional

# alias / legacy symbol -> HGNC-approved symbol
_ALIASES: Dict[str, str] = {
    "HER2": "ERBB2",  # HGNC:3430 -- the collision this dataset actually contains
    "HER2NEU": "ERBB2",
    "NEU": "ERBB2",
    "P53": "TP53",  # HGNC:11998
    "TRP53": "TP53",
    "CMET": "MET",  # HGNC:7029
    "CMYC": "MYC",  # HGNC:7553
    "CKIT": "KIT",  # HGNC:6342
    "HER1": "EGFR",  # HGNC:3236
    "ERBB1": "EGFR",
    "FLT2": "FGFR1",  # HGNC:3688
    "MLL": "KMT2A",  # HGNC:7132
}


def _key(symbol: str) -> str:
    """Fold case and punctuation, so `her-2`, `HER 2` and `HER2` are one request."""
    return re.sub(r"[^A-Z0-9]", "", str(symbol).strip().upper())


def canonical(symbol: str) -> str:
    """The HGNC-approved symbol for a caller's spelling."""
    key = _key(symbol)
    return _ALIASES.get(key, key)


def rewrite_of(symbol: str) -> Optional[Dict[str, str]]:
    """The provenance of a rewrite, when one happened.

    Note this cannot tell you a symbol is unknown: `ZZZZ9` comes back unrewritten, exactly like an
    approved symbol would. Deciding a gene is absent is the data layer's job, against the loaded
    frame -- never this module's guess.
    """
    approved = canonical(symbol)
    recorded = str(symbol).strip()
    return {"from": recorded, "to": approved} if _key(recorded) != approved else None
