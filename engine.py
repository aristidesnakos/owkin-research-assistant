"""The agent loop: a question in, a routed and traced answer out.

The model chooses which skill to call and with what arguments, and writes the framing
sentences. It does not write the numbers. The prompt forbids it and, more to the point, the
adapters never read a number out of the model's prose: they render the table straight from
`skill_calls[-1].result`. The guarantee is therefore structural rather than promised -- there
is no path by which a model-authored digit reaches the screen.
"""
from __future__ import annotations

# Before any project import: data.py resolves OWKIN_DATA_PATH from the environment, and an
# import that beats load_dotenv() reads it before .env has been applied.
from dotenv import load_dotenv

load_dotenv()

import json  # noqa: E402
import os  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from typing import Any, Callable, Dict, List, Optional  # noqa: E402

from openai import OpenAI, OpenAIError  # noqa: E402

import skills  # noqa: E402
from data import available_genes, available_indications  # noqa: E402

MAX_STEPS = 6
TIMEOUT_S = 30  # the SDK retries with backoff on its own; the defect was the 600s default


class ConfigurationError(RuntimeError):
    """The product is unconfigured, not broken. Adapters show the message, never a traceback."""


NO_API_KEY = (
    "I need an OpenRouter API key before I can answer anything. This is a setup step, not a "
    "fault: create a file named .env next to this app, put OPENROUTER_API_KEY=sk-or-... in it, "
    "then start me again."
)

# Layer 1 (always visible): we changed an identifier on the reader. True in both directions --
# the user typed HER2, or the user typed nothing and the file said HER2 -- because either way
# the symbol on screen is not the symbol in the CSV, and that is an inference we made for them.
# Two halves, because they answer different questions and only one of them generalises.
#
# The identity: what the two symbols ARE. Generic, so it holds for all twelve aliases.
REWRITE_IDENTITY = "{frm} and {to} are two names for the same gene."

# The gloss: the same fact, told properly, for the one alias a reader of this dataset actually
# meets -- HER2 is the reason the breast cohort is interesting at all. Keyed by approved symbol.
# It REPLACES the identity line rather than joining it, or the reader is told twice in two
# paragraphs that these are the same gene, which reads like a stutter and gets skimmed.
REWRITE_GLOSS: Dict[str, str] = {
    "ERBB2": (
        "HER2 (Human Epidermal growth factor Receptor 2) and ERBB2 (Erb-B2 Receptor Tyrosine "
        "Kinase 2) are two names for the same exact thing. ERBB2 is the official name of the "
        "gene, while HER2 is the name of the protein it creates. Together, they act as an "
        '"on-switch" that tells cells when to grow and divide.'
    ),
}

# The disclosure: what WE did to the symbol. Always shown, under whichever of the two above ran,
# because this is the part the reader is owed -- the name on screen is not the name they gave us.
#
# It does NOT say "the dataset records it as {frm}", which is what it used to say and which is not
# always true: `frm` is the symbol that was ASKED FOR, not the one on disk. Ask for NEU (an alias
# genes.py knows) and that sentence claimed the CSV holds "NEU". It holds HER2. A false statement
# about the data, in the one panel whose whole job is to be straight about the data.
REWRITE_NOTE = (
    "{to} is the current approved symbol for {frm}; this answer uses it throughout, so one gene "
    "has one name. Asking for either name reaches the same row."
)

# The load-bearing sentence of the whole product: absence of evidence, rendered as an answer
# rather than as an error, and explicitly not rendered as evidence of absence.
# `cancer` is the user's own wording, so the sentence must not append a noun to it: they may
# have typed "esophageal", or "esophageal cancer", or "oesophageal carcinoma".
NOT_IN_DATASET = (
    "This is a gap in the data I was given, not a finding about {cancer}. Please do not read "
    "it as 'no genes are involved' -- I simply have no rows for it."
)

TRACE_NOTE = (
    "Every value above was computed by pandas over the CSV and is rendered directly from the "
    "skill result. The model chose which skill to call with which arguments; it did not "
    "produce, transform or round any number."
)

_IMPLS: Dict[str, Callable[..., Any]] = {
    "get_targets": skills.get_targets,
    "get_expressions": skills.get_expressions,
    "get_gene_profile": skills.get_gene_profile,
    "describe_capabilities": skills.describe_capabilities,
}


def _system_prompt() -> str:
    """Generated from the dataset, so it cannot drift from it.

    The gene vocabulary is injected alongside the indications. Without it the model supplies
    symbols from its own prior -- which is how a question about ERBB2 in breast cancer, where
    the file records the same gene as HER2, became a confident false denial.
    """
    return f"""You are K-mini. You answer questions from ONE frozen dataset: the median value \
recorded for a (gene, cancer indication) pair. You have no other data, and you never answer \
about this dataset from memory.

Skills -- call them with exactly these arguments:
  get_targets(cancer_name)            -> {{status, cancer, genes, resolved, available}}
  get_expressions(genes, cancer_name) -> {{status, cancer, values, not_found, resolved, note}}
  get_gene_profile(genes)             -> {{status, profiles, not_found, resolved, note}}
  describe_capabilities()             -> {{status, dataset, i_can, i_cannot, indications}}

Routing:
  genes involved in a cancer   -> get_targets(that cancer)
  median values for a cancer   -> get_targets(cancer), then get_expressions(those genes, cancer)
  a gene, no cancer named      -> get_gene_profile(gene). Never get_expressions: a median
                                  belongs to a (gene, cancer) pair, and TP53 spans eight of them.
  what can you do              -> describe_capabilities()

ALWAYS call a skill before you answer, even when you are confident. In particular, a cancer you
believe is absent from the dataset is still a question for get_targets -- it accepts any wording,
and it is the only thing that knows. Answering "that is not in the dataset" from your own memory
is a guess that happens to be right, and it reaches the user with no evidence attached.

Rules:
1. YOU DO NOT WRITE NUMBERS OR GENE LISTS. The interface renders the genes and their values
   directly from the skill result, as a table, and it renders the capability list too. Write one
   or two sentences of framing and let them speak. Do not restate, summarise or duplicate a list
   the interface is already showing. Never state, average, round or recall a median value.
2. Route on the result's `status`, never on whether a list is empty. `unknown_indication`
   means this dataset holds no cohort for that term: say the dataset has no rows for it, say
   that this is a gap in the data rather than a fact about the cancer, and stop. Never answer
   about a different, similar cohort instead -- a correct number about the wrong cancer is the
   worst thing you could hand back.
3. Genes in `not_found` are absent from THIS FILE, in any cohort. That is not a statement
   about biology and not a failure to recognise the gene -- EGFR lands in `not_found`, and
   EGFR is one of the best-characterised oncogenes there is. Say "this dataset has no row for
   EGFR"; never "EGFR is not involved in".
4. If a result carries `resolved`, say the symbol was rewritten (HER2 is recorded under its
   approved symbol, ERBB2).
5. Never give a value ACROSS genes -- no median, mean, average or "overall" expression for a
   cancer. No such skill exists, because no such number does: a median of medians aggregates
   over genes rather than samples and has no biological referent. The per-gene table IS the
   answer to that question, so still fetch it with get_expressions and let the interface show
   it -- refuse the one number by giving them the many, not by giving them nothing.
6. Never describe magnitude ("high", "low", "elevated", "overexpressed"), never rank or
   compare genes, never assert significance, correlation or effect size, and never name a
   unit. This dataset records no unit, no sample size and no dispersion, so none of that is
   available to you.
7. Answer a capability question from describe_capabilities(), never from memory.
8. Write for a non-technical stakeholder: short, plain, no hedging rituals.

Indications in this dataset: {', '.join(available_indications())}.
Gene symbols in this dataset (HGNC-approved -- use these spellings): \
{', '.join(available_genes())}."""


_GENES_PARAM = {
    "type": "array",
    "items": {"type": "string"},
    "description": (
        "Gene symbols, as an array -- never a bare string. Aliases resolve to the approved "
        "symbol (HER2 -> ERBB2) and the rewrite is reported back to you in `resolved`."
    ),
}

# Required, and constrained to the dataset's own vocabulary, read at import. A median value is a
# property of a (gene, cancer) pair -- TP53 is 0.233 in breast and 0.071 in gastric -- so a call
# that omits the cohort has to choose one, and choosing is computing. The enum is the second lock:
# no number can be attached to a cohort this file does not hold.
_COHORT_PARAM = {
    "type": "string",
    "enum": available_indications(),
    "description": (
        "Required. The cancer cohort, as one of the dataset's own keys. If the user asks about "
        "a cohort that is not listed here, do not substitute the nearest one: check it with "
        "get_targets, which will tell you it is absent."
    ),
}

# Deliberately NOT enum-constrained, and this is the one place that is right. The enum exists to
# stop a value being attached to the wrong cohort; here there is no value. What we need instead is
# a route by which a term the dataset does not hold -- "esophageal" -- reaches the resolver and
# comes back refused, in code, with the available cohorts attached. Constrain this and the model
# cannot ask the question, so it answers the user from its own head instead, and the refusal we
# carefully authored in skills.py becomes unreachable. Substitution is prevented by the resolver,
# not by the schema.
_TERM_PARAM = {
    "type": "string",
    "description": (
        "Required. The cancer the user asked about, in their own words. Any term is permitted: "
        "if this dataset holds no cohort for it, the skill says so and lists what it does hold."
    ),
}


def _tool(name: str, description: str, properties: Dict[str, Any]) -> Dict[str, Any]:
    """Flat primitives and enums only -- no nested objects, no oneOf. Tool-calling reliability
    should not depend on one provider's handling of an exotic schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }


SKILL_SCHEMAS: List[Dict[str, Any]] = [
    _tool(
        "get_targets",
        "The genes this dataset holds rows for in one cancer cohort. These are genes present in "
        "the file, not validated drug targets. Call this first for any question about a cancer, "
        "including one you suspect is absent: it is how you find out. Read `status`, not the "
        "length of `genes`.",
        {"cancer_name": _TERM_PARAM},
    ),
    _tool(
        "get_expressions",
        "The recorded median value of each gene within one cancer cohort. Every gene you ask "
        "for comes back either in `values` or in `not_found`, so absence is stated rather than "
        "implied by omission.",
        {"genes": _GENES_PARAM, "cancer_name": _COHORT_PARAM},
    ),
    _tool(
        "get_gene_profile",
        "Every (cancer, median_value) pair this dataset holds for a gene. The right skill when "
        "the question names a gene but no cohort: it cannot collapse eight cohorts to a scalar.",
        {"genes": _GENES_PARAM},
    ),
    _tool(
        "describe_capabilities",
        "What this assistant can and cannot answer. Authored in code, so it cannot overclaim. "
        "Call this for any question about your own capabilities.",
        {},
    ),
]

_PARAMS = {s["function"]["name"]: s["function"]["parameters"] for s in SKILL_SCHEMAS}


@dataclass
class SkillCall:
    name: str
    arguments: Dict[str, Any]
    result: Any


@dataclass
class AnswerObject:
    """Model prose, plus the skill results the adapters actually render."""

    text: str
    skill_calls: List[SkillCall] = field(default_factory=list)
    # Read from the environment at construction, not bound as a dataclass default: a default is
    # evaluated once, at import, and would stamp every answer with whatever model loaded first.
    model: str = field(default_factory=lambda: os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"))

    def result(self, *names: str) -> Optional[Dict[str, Any]]:
        """The latest result from any of `names`. This is what an adapter renders."""
        for call in reversed(self.skill_calls):
            if call.name in names and isinstance(call.result, dict):
                return call.result
        return None

    def rewrites(self) -> List[Dict[str, str]]:
        """Every symbol we rewrote, deduplicated. Always shown: the reader is looking at a
        symbol that is not the one in the file, and that is our inference, not their request."""
        seen = {r["from"]: r for c in self.skill_calls if isinstance(c.result, dict)
                for r in c.result.get("resolved", [])}
        return [seen[k] for k in sorted(seen)]


def _validate(name: str, arguments: Any) -> Optional[Dict[str, Any]]:
    """Check a call against its schema; return an error result the model can read, or None.

    A malformed call is a routing mistake, and the model is the only thing that can fix it --
    so it goes back as a tool-role message, never as an exception and never as a bare string
    that `list()` will happily shred into characters.
    """
    params = _PARAMS.get(name)
    if params is None:
        return {"status": "unknown_skill", "error": f"no skill named {name!r}",
                "available": sorted(_PARAMS)}
    if not isinstance(arguments, dict):
        return {"status": "invalid_arguments", "error": "arguments must be a JSON object"}

    props: Dict[str, Any] = params["properties"]
    for key in props:
        if key not in arguments:
            return {"status": "invalid_arguments", "error": f"missing required argument {key!r}",
                    "expected": params}
    for key, value in arguments.items():
        spec = props.get(key)
        if spec is None:
            return {"status": "invalid_arguments", "error": f"unknown argument {key!r}",
                    "expected": params}
        if spec["type"] == "array" and not (
            isinstance(value, list) and value and all(isinstance(v, str) for v in value)
        ):
            return {"status": "invalid_arguments",
                    "error": f"{key!r} must be a non-empty array of strings; a bare string is "
                             f"not a gene list", "expected": params}
        if spec["type"] == "string":
            if not isinstance(value, str):
                return {"status": "invalid_arguments",
                        "error": f"{key!r} must be a string", "expected": params}
            if value not in spec.get("enum", [value]):
                return {"status": "invalid_arguments",
                        "error": f"{key!r}={value!r} is not a cohort this dataset holds. "
                                 f"Permitted: {spec['enum']}. Report it as absent; do not "
                                 f"substitute another cohort.", "expected": params}
    return None


def _dispatch(name: str, arguments: Any) -> Any:
    """Validate, then call. Never raises: a skill bug is an answer, not a crash."""
    error = _validate(name, arguments)
    if error is not None:
        return error
    try:
        return _IMPLS[name](**arguments)
    except Exception as exc:
        return {"status": "skill_error", "error": f"{type(exc).__name__}: {exc}"}


def answer(query: str) -> AnswerObject:
    """Answer a question, returning the model's framing plus the skill results behind it."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ConfigurationError(NO_API_KEY)

    client = OpenAI(
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=key,
        timeout=TIMEOUT_S,
    )
    model = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": query},
    ]
    calls: List[SkillCall] = []

    for _ in range(MAX_STEPS):
        try:
            reply = client.chat.completions.create(
                model=model, messages=messages, tools=SKILL_SCHEMAS, temperature=0
            ).choices[0].message
        except OpenAIError as exc:
            raise ConfigurationError(f"I could not reach the model provider: {exc}") from exc

        if not reply.tool_calls:
            return AnswerObject(text=reply.content or "", skill_calls=calls, model=model)

        messages.append({
            "role": "assistant",
            "content": reply.content or None,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in reply.tool_calls
            ],
        })
        for tc in reply.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                args, result = {}, {"status": "invalid_arguments",
                                    "error": f"arguments were not valid JSON: {exc}"}
            else:
                result = _dispatch(tc.function.name, args)
            calls.append(SkillCall(tc.function.name, args, result))
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, default=str)})

    return AnswerObject(
        text=f"I could not finish this within my budget of {MAX_STEPS} steps. The partial "
             "trace is below.",
        skill_calls=calls,
        model=model,
    )
