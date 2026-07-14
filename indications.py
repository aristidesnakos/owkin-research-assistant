"""Cohort vocabulary: the user's word for a cancer, mapped to a dataset key -- or refused.

Two outcomes, and there is deliberately no third. Either the term is a cohort this file holds, or
it is out of vocabulary. There is no "nearest match" tier, because handing back a correct number
about the wrong cancer is the worst thing this system could do: `esophageal` is not `gastric` --
they are different diseases, and gastric is a sibling of esophageal, never a parent. It resolves
to nothing, by construction. That is a default-deny, not a blocklist: a blocklist of forbidden
terms is a hand-maintained surface that drifts, and the absence of a table entry already does the
work.

Subtypes are refused for the same reason, and this is a scientific judgement, not a gap. Answering
"ESR1 in TNBC" from the breast cohort is not an approximation: TNBC is ER-negative *by definition*,
while the breast cohort is unselected and majority ER-positive -- so the answer would be biased at
exactly the gene that was asked about. A refusal that names what is missing is more useful than a
number that is wrong in a direction the reader cannot see.
"""
from __future__ import annotations

import re
from typing import Dict, Optional

from data import available_indications

# Suffixes that distinguish no cohort in this file from another, so stripping one can only help.
_SUFFIXES = (" cancer", " carcinoma", " tumor", " tumour", " adenocarcinoma")

# Synonyms: another name for the SAME cohort. Never a narrowing of one, and never a widening
# either -- the entry must denote the same set of patients, or it does not belong here.
#
# That rule is load-bearing and this table used to break it. `nsclc -> lung` shipped, while
# `sclc` resolved to nothing: two subtypes of one cohort, one silently approximated and one
# refused, which is not a defensible position to hold in either direction. Also gone:
# `colon`/`rectal` (subsites of colorectal, not colorectal), and `skin -> melanoma`, which is
# the same error inverted -- most skin cancers are basal or squamous cell, whose biology is not
# melanoma's, so it answered a broad question from a narrow cohort. All four now resolve to
# None and the caller says what it does hold, which is the honest answer.
_SYNONYMS: Dict[str, str] = {
    "rcc": "renal",
    "renal cell": "renal",
    "kidney": "renal",
    "gbm": "glioblastoma",
    "glioblastoma multiforme": "glioblastoma",
    "crc": "colorectal",
    "bowel": "colorectal",
    "stomach": "gastric",
    "pancreas": "pancreatic",
    "ovary": "ovarian",
}


def _key(term: str) -> str:
    """Fold case, punctuation and a trailing suffix: 'Renal Cell Carcinoma' and 'RCC' are one."""
    t = re.sub(r"[^a-z0-9 ]", " ", str(term).strip().lower())
    t = re.sub(r"\s+", " ", t).strip()
    for suffix in _SUFFIXES:
        if t.endswith(suffix):
            return t[: -len(suffix)].strip()
    return t


def resolve(term: str) -> Optional[str]:
    """The dataset key for a cohort term, or None if this file does not hold it."""
    key = _key(term)
    if key in available_indications():
        return key
    return _SYNONYMS.get(key)
