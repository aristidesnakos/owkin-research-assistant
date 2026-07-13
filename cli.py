"""Plain-text adapter. Same contract as app.py: the prose is the model's, the table is the
skill result's. ASCII only -- the reviewer may be on a Windows console in cp1252, and a pretty
table that raises UnicodeEncodeError on their laptop is worth less than an ugly one that does not.
"""
from __future__ import annotations

import json
import sys
import textwrap

import skills
from engine import (
    NOT_IN_DATASET,
    REWRITE_GLOSS,
    REWRITE_IDENTITY,
    REWRITE_NOTE,
    TRACE_NOTE,
    AnswerObject,
    ConfigurationError,
    answer,
)

WIDTH = 78
RULE = "-" * WIDTH


def _wrap(text: str, indent: str = "  ", hang: str = "") -> str:
    return "\n".join(
        textwrap.fill(line, WIDTH, initial_indent=indent, subsequent_indent=hang or indent)
        for line in text.splitlines() if line.strip()
    )


def _bullets(items: list[str]) -> list[str]:
    return [_wrap(f"- {x}", "    ", "      ") for x in items]


def render(a: AnswerObject) -> str:
    """The answer, then what we changed, then how to read it, then how it was computed."""
    out = [_wrap(a.text, "")]
    expressions = a.result("get_expressions")
    targets = a.result("get_targets")
    capabilities = a.result("describe_capabilities")

    # Alphabetical, never by value: a value-ordered table is the sentence "this one is highest",
    # written as layout, and without a unit these genes share no scale to be ranked on.
    if expressions and expressions.get("values"):
        out += ["", "  GENE            MEDIAN VALUE"]
        out += [f"  {gene:<16}{value:>12.3f}" for gene, value in sorted(expressions["values"].items())]
    elif targets and targets.get("genes"):
        out += ["", _wrap("  ".join(sorted(targets["genes"])))]

    if capabilities:
        out += ["", _wrap(capabilities["dataset"]), "", "  I CAN"] + _bullets(capabilities["i_can"])
        out += ["", "  I WILL NOT"] + _bullets(capabilities["i_cannot"])

    for result in (expressions, targets):
        if result and result.get("status") == "unknown_indication":
            out += ["", _wrap(NOT_IN_DATASET.format(cancer=result["cancer"])), "",
                    _wrap("The indications I do have: " + ", ".join(result["available"]))]
            break

    # The gloss (what the gene is) leads, falling back to the generic identity line; the
    # disclosure (what we renamed, and why the screen disagrees with the file) always follows.
    for rewrite in a.rewrites():
        lead = REWRITE_GLOSS.get(rewrite["to"]) or REWRITE_IDENTITY.format(
            frm=rewrite["from"], to=rewrite["to"]
        )
        out += ["", _wrap(lead)]
        out += ["", _wrap(REWRITE_NOTE.format(frm=rewrite["from"], to=rewrite["to"]))]

    if expressions and expressions.get("values"):
        out += ["", RULE, "How to read these numbers", "", _wrap(skills.UNIT_NOTE)]
        if len(expressions["values"]) > 1:
            out += ["", _wrap(skills.AGGREGATE_NOTE)]

    if a.skill_calls:
        n = len(a.skill_calls)
        out += ["", RULE, f"How I got this: {n} skill call{'s' if n > 1 else ''}, "
                          "0 numbers from the model", ""]
        for call in a.skill_calls:
            out += [_wrap(f"{call.name}({json.dumps(call.arguments)})"),
                    _wrap(f"-> {json.dumps(call.result, default=str)}", "      ")]
        out += ["", _wrap(TRACE_NOTE), "", _wrap(f"model {a.model} @ temperature 0 (routing only)")]

    return "\n".join(out)


def main() -> int:
    # The model's prose may contain a character the console cannot encode; a Windows cp1252
    # terminal would raise UnicodeEncodeError and lose an answer that was otherwise correct.
    sys.stdout.reconfigure(errors="replace")

    query = " ".join(sys.argv[1:]).strip()
    try:
        if query:
            print(render(answer(query)))
            return 0
        print("K-mini. Ask about a cancer indication in this dataset. Ctrl-C to exit.")
        while True:
            try:
                query = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if query:
                print()
                print(render(answer(query)))
    except ConfigurationError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
