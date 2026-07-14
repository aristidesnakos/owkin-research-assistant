"""Evals for K-mini. Run: python evals.py

Tier 1 (always, no API key, no network): deterministic assertions on skills.py. Every expected
value is derived from the CSV at test time, never hardcoded -- the old suite asserted
`get_expressions(["BRCA2"]) == 0.032`, which encodes CSV ROW ORDER (BRCA2 has a different
recorded value per cohort), not biology, and so pinned the very bug it existed to catch.
`mutation_test()` below checks that THIS suite would notice if its ground truth and the
implementation drifted; if it stayed green while the data changed, everything above it is
decorative.

Tier 2 (only if OPENROUTER_API_KEY is set): the four canonical queries from the README, end to
end through engine.answer(). Asserts the right skill fired with the right arguments (an
indication-scoped call must carry cancer_name) and that every number in the answer text is
grounded in a skill result.

Deliberately not built: multi-model sweeps, N-trial flakiness loops, a separate test file for
the scorers, and a regex "forbidden lexicon" gate -- the last is unsound, since a correct
refusal that NAMES the forbidden term ("I cannot say this is statistically significant") would
fail it. None of that is needed to answer the only question that matters: does this work.
"""
from __future__ import annotations

import csv
import os
import re
import subprocess
import sys
import tempfile
from typing import Any, Callable, Dict, List

from dotenv import load_dotenv

load_dotenv()

ROOT = os.path.dirname(os.path.abspath(__file__))
_FAILURES: List[str] = []
_N = 0

def check(name: str, fn: Callable[[], object]) -> bool:
    """`fn` returns truthy to pass, or raises. A raise is a FAIL, never a crash."""
    global _N
    _N += 1
    try:
        ok, detail = bool(fn()), ""
    except Exception as exc:  # noqa: BLE001 -- a broken skill must print FAIL, not vanish
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail else ""))
    if not ok:
        _FAILURES.append(name)
    return ok

# --- ground truth, read straight from the CSV at test time. No import of skills/data/genes:
# an expectation derived by the code under test is not an expectation, it is a tautology.

def _csv_path() -> str:
    return os.environ.get("OWKIN_DATA_PATH") or os.path.join(ROOT, "docs", "owkin_take_home_data.csv")

def _rows(path: str = "") -> List[tuple]:
    with open(path or _csv_path(), newline="", encoding="utf-8") as fh:
        return [(r["cancer_indication"].strip().lower(), r["gene"].strip(), float(r["median_value"]))
                for r in csv.DictReader(fh)]

def _raw_value(indication: str, gene_as_recorded: str) -> float:
    matches = [v for i, g, v in _rows() if i == indication and g == gene_as_recorded]
    assert len(matches) == 1, f"{gene_as_recorded} in {indication}: {len(matches)} rows"
    return matches[0]

# =============================== Tier 1 ====================================================

def tier1() -> None:
    print("== TIER 1 -- deterministic, no API key, no network ==")
    import skills  # imported here so a broken import is a FAIL line, not a crash on `import evals`

    # The headline bug: HER2/ERBB2 is one gene, recorded under a different name per cohort.
    check(
        "HER2 (breast) and ERBB2 (gastric) resolve to the same gene, at the CSV's own value",
        lambda: skills.get_expressions(["ERBB2"], "breast")["values"].get("ERBB2") == _raw_value("breast", "HER2")
        and skills.get_expressions(["HER2"], "gastric")["values"].get("ERBB2") == _raw_value("gastric", "ERBB2"),
    )
    check(
        "asking for HER2 in gastric surfaces the rewrite (resolved), never a silent swap",
        lambda: bool(skills.get_expressions(["HER2"], "gastric")["resolved"]),
    )

    # No drop_duplicates / row-order selection: a (gene, cohort) pair is scoped correctly.
    check(
        "get_expressions(BRCA2, prostate) is prostate's own row -- not breast's, by file order",
        lambda: skills.get_expressions(["BRCA2"], "prostate")["values"]["BRCA2"] == _raw_value("prostate", "BRCA2")
        and _raw_value("prostate", "BRCA2") != _raw_value("breast", "BRCA2"),
    )
    check(
        "get_gene_profile(BRCA2) returns every cohort's row, not one picked by file order",
        lambda: skills.get_gene_profile(["BRCA2"])["profiles"]["BRCA2"] == [
            {"cancer": i, "median_value": v} for i, g, v in sorted(_rows()) if g == "BRCA2"
        ],
    )

    # Absence is stated, never implied by omission.
    check(
        "EGFR (zero rows in this CSV) comes back in not_found, not a silent {}",
        lambda: "EGFR" in skills.get_expressions(["EGFR"], "breast")["not_found"],
    )
    lung_genes = {g for i, g, _ in _rows() if i == "lung"}
    assert "TP53" not in lung_genes, "fixture assumption broke: TP53 is now recorded in lung"
    check(
        "TP53 (known elsewhere) is also 'not_found' in lung -- absence stated, not omitted",
        lambda: "TP53" in skills.get_expressions(["TP53"], "lung")["not_found"],
    )

    # Esophageal is out-of-vocabulary and never resolves to gastric or any other cohort.
    check(
        "esophageal cancer resolves to no cohort at all (never gastric)",
        lambda: skills.get_targets("esophageal cancer")["status"] == "unknown_indication"
        and skills.get_targets("esophageal cancer")["genes"] == [],
    )
    check(
        "get_expressions also refuses esophageal rather than substituting a cohort",
        lambda: skills.get_expressions(["TP53"], "esophageal cancer")["status"] == "unknown_indication",
    )

    # A bare string is one gene, not four characters.
    check(
        "get_expressions('TP53', ...) -- a bare string -- is one gene, not list('TP53')",
        lambda: set(skills.get_expressions("TP53", "breast")["values"]) == {"TP53"}
        and skills.get_expressions("TP53", "breast")["not_found"] == [],
    )

    # There is no across-gene aggregate anywhere in skills.py.
    own = [n for n in dir(skills) if not n.startswith("_") and callable(getattr(skills, n))
           and getattr(getattr(skills, n), "__module__", None) == "skills"]
    check(
        "skills.py exposes exactly its four documented skills -- no aggregate/summarize function",
        lambda: set(own) == {"get_targets", "get_expressions", "get_gene_profile", "describe_capabilities"},
    )

    # Every tool schema must agree, name for name, with the function it dispatches to. The engine
    # calls `_IMPLS[name](**arguments)`, so a schema that advertises `genes` while the function
    # takes `genes_requested` is not a style inconsistency -- it is a skill that raises TypeError on
    # every call. That shipped: the flagship breast-cancer query (get_targets, then get_expressions)
    # was dead, and Tier 2 stayed green, because it asserted the call was MADE and never that it
    # SUCCEEDED. This check needs no key and no network, and it is the reason that cannot recur.
    import inspect

    import engine

    def schema_matches_signature() -> bool:
        for tool in engine.SKILL_SCHEMAS:
            fn = tool["function"]
            name = fn["name"]
            declared = set(fn["parameters"].get("properties", {}))
            actual = set(inspect.signature(engine._IMPLS[name]).parameters)
            assert declared == actual, (
                f"{name}: schema declares {sorted(declared)}, "
                f"but the function takes {sorted(actual)} -- the engine passes the model's "
                f"arguments straight through as **arguments, so this skill cannot be called"
            )
        return True

    check(
        "every tool schema's parameters match its function's signature -- a skill the model is "
        "told to call is a skill that can actually be called",
        schema_matches_signature,
    )

    # The docs must not claim what the code does not do -- this repo's most damaging bug class,
    # because a reviewer falsifies it by reading two files. DATA_DICTIONARY.md quotes UNIT_NOTE and
    # names skills.py as the source of truth; it once quoted a version that no longer existed in
    # code, and separately claimed an eval enforced the agreement when no such eval existed. It
    # exists now, and it is why the quote may be trusted.
    def dictionary_quotes_the_real_note() -> bool:
        path = os.path.join(ROOT, "docs", "DATA_DICTIONARY.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        assert skills.UNIT_NOTE in text, (
            "docs/DATA_DICTIONARY.md no longer quotes skills.UNIT_NOTE verbatim -- the document "
            "says the code is the source of truth, so the document is now stale"
        )
        return True

    check(
        "docs/DATA_DICTIONARY.md quotes skills.UNIT_NOTE verbatim -- the doc cannot drift from "
        "the caveat users actually see",
        dictionary_quotes_the_real_note,
    )

    mutation_test()

_MUTATION_PROBE = """
import sys
sys.path.insert(0, {root!r})
import skills
print(skills.get_expressions(["{gene}"], "{ind}")["values"]["{gene}"])
"""

def mutation_test() -> None:
    """Perturb one median_value in a COPY of the CSV, point OWKIN_DATA_PATH at it, and demand
    the value read here (from the ORIGINAL file) disagrees with what the skill now returns. If
    it agreed, every value assertion above would be tautological -- proof the implementation
    moved, never proof the expectation was ever right."""
    ind, gene = "breast", "TP53"
    original = _raw_value(ind, gene)
    bumped = round(1.0 - original, 3)

    def mutated_disagrees() -> bool:
        with open(_csv_path(), encoding="utf-8") as fh:
            text = fh.read()
        old_line = f"{ind},{gene},{original}"
        assert old_line in text, f"{old_line!r} not found verbatim in the CSV"
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
            fh.write(text.replace(old_line, f"{ind},{gene},{bumped}"))
            path = fh.name
        try:
            out = subprocess.run(
                [sys.executable, "-c", _MUTATION_PROBE.format(root=ROOT, gene=gene, ind=ind)],
                capture_output=True, text=True, timeout=60, cwd=ROOT,
                env={**os.environ, "OWKIN_DATA_PATH": path},
            )
            if out.returncode != 0:
                raise RuntimeError(out.stderr.strip().splitlines()[-1] if out.stderr else "probe crashed")
            seen = float(out.stdout.strip())
        finally:
            os.unlink(path)
        # The skill moved with the mutated file; the truth read here, from the original file,
        # did not -- a suite that could not tell them apart would be measuring nothing.
        return abs(seen - bumped) < 1e-9 and abs(seen - original) > 1e-9

    check(
        "mutating a median_value in the CSV changes what the skill returns -- so a hardcoded "
        "or stale expectation WOULD have turned this suite red",
        mutated_disagrees,
    )

# =============================== Tier 2 ====================================================
# The four canonical queries from README.md, end to end through the live agent.

CANONICAL_QUERIES: List[Dict[str, Any]] = [
    dict(id="Q1-capabilities", query="How can you help me?",
         expect_calls=["describe_capabilities"]),
    dict(id="Q2-lung-genes", query="What are the main genes involved in lung cancer?",
         expect_calls=["get_targets"], expect_args={"get_targets": {"cancer_name": "lung"}},
         # Content, not just routing. Without this, get_targets returning {"status":"ok","genes":[]}
         # passes every other check on this query and renders an answer with no genes in it.
         expect_genes=sorted({g for i, g, _ in _rows() if i == "lung"})),
    dict(id="Q3-breast-expressions",
         query="What is the median value expression of genes involved in breast cancer?",
         expect_calls=["get_targets", "get_expressions"],
         expect_args={"get_targets": {"cancer_name": "breast"},
                      "get_expressions": {"cancer_name": "breast"}},
         # The flagship query, and the one that shipped broken. Grounding alone cannot catch that:
         # it asks whether the numbers present are real, and is vacuously true when there are none.
         # So demand the numbers exist, and that they are the CSV's own. HER2 is spelled out here,
         # not imported from genes.py: an expectation borrowed from the code under test is a
         # tautology, and HGNC:3430 is a fact about the gene, not about this repo.
         expect_values={("ERBB2" if g == "HER2" else g): v for i, g, v in _rows() if i == "breast"}),
    dict(id="Q4-esophageal",
         query="What is the median value expression of genes involved in esophageal cancer?",
         forbid_real_cohort=True),
]

_DECIMAL = re.compile(r"(?<![\w.])(\d+\.\d+)(?!\d)")

def _numbers(obj: Any):
    """Every number anywhere in a skill result, at any depth."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield float(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _numbers(v)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from _numbers(v)

def tier2() -> None:
    print("\n== TIER 2 -- the four canonical queries, live, via OpenRouter ==")
    import engine

    real_indications = set(engine.available_indications())

    for c in CANONICAL_QUERIES:
        box: Dict[str, Any] = {}

        def run(c=c, box=box) -> bool:
            box["answer"] = engine.answer(c["query"])
            return True

        if not check(f"{c['id']}: {c['query']!r} answered without raising", run):
            continue
        answer, names = box["answer"], [sc.name for sc in box["answer"].skill_calls]

        # Every skill call must SUCCEED, not merely happen. Without this, a query whose every call
        # raised TypeError still passed: routing saw the call was made, arguments saw what was sent,
        # and grounding passed vacuously, since a failed lookup puts no numbers in the answer to
        # check. `engine._dispatch` catches skill exceptions and returns them as a result, by
        # design -- a skill bug is an answer, not a crash -- so nothing else here would ever notice.
        #
        # Whitelisted, not blacklisted. Checking `status != "skill_error"` let `invalid_arguments`
        # through, so a schema/validator mismatch that bounced every call stayed invisible. These
        # two are the only statuses that mean the skill did its job -- `unknown_indication` very
        # much included: refusing esophageal IS the skill working.
        def every_call_ok(answer=answer) -> bool:
            good = {"ok", "unknown_indication"}
            broken = [f"{sc.name} -> {sc.result.get('status')}: {sc.result.get('error', '')}".strip()
                      for sc in answer.skill_calls
                      if not (isinstance(sc.result, dict) and sc.result.get("status") in good)]
            assert not broken, "; ".join(broken)
            return True

        check(f"{c['id']}: every skill call returned a usable result (ok / unknown_indication)",
              every_call_ok)

        if c.get("expect_genes"):
            def genes_ok(c=c, answer=answer) -> bool:
                got: set = set()
                for sc in answer.skill_calls:
                    if sc.name == "get_targets" and isinstance(sc.result, dict):
                        got |= set(sc.result.get("genes") or [])
                assert got, "get_targets returned no genes at all -- the answer would list none"
                missing = set(c["expect_genes"]) - got
                assert not missing, f"missing from the listing: {sorted(missing)}"
                return True

            check(f"{c['id']}: the cohort's genes are all present, and are the CSV's own", genes_ok)

        for skill in c.get("expect_calls", []):
            check(f"{c['id']} routing: {skill} was called (called {names})",
                  lambda skill=skill, names=names: skill in names)

        for skill, expected in c.get("expect_args", {}).items():
            def args_ok(skill=skill, expected=expected, answer=answer) -> bool:
                matching = [sc for sc in answer.skill_calls if sc.name == skill]
                return any(all(sc.arguments.get(k) == v for k, v in expected.items()) for sc in matching)
            check(f"{c['id']} arguments: {skill} carries {expected}", args_ok)

        if c.get("expect_values"):
            def values_ok(c=c, answer=answer) -> bool:
                got: Dict[str, float] = {}
                for sc in answer.skill_calls:
                    if sc.name == "get_expressions" and isinstance(sc.result, dict):
                        got.update(sc.result.get("values") or {})
                expected = c["expect_values"]
                assert got, "get_expressions returned no values at all -- the table would be empty"
                missing = set(expected) - set(got)
                assert not missing, f"never looked up: {sorted(missing)}"
                wrong = {g: (got[g], expected[g]) for g in expected if abs(got[g] - expected[g]) > 1e-9}
                assert not wrong, f"value disagrees with the CSV: {wrong}"
                return True

            check(f"{c['id']}: every breast gene's median is present and is the CSV's own value",
                  values_ok)

        if c.get("forbid_real_cohort"):
            check(
                f"{c['id']}: no call substitutes a real cohort for the absent one",
                lambda answer=answer: not any((sc.arguments or {}).get("cancer_name") in real_indications
                                              for sc in answer.skill_calls),
            )

        def grounded(answer=answer) -> bool:
            available = {round(v, 6) for v in _numbers([sc.result for sc in answer.skill_calls])}
            return all(round(float(lit), 6) in available for lit in _DECIMAL.findall(answer.text or ""))

        check(f"{c['id']} grounding: every number in the answer text traces to a skill result", grounded)

def main() -> int:
    tier1()
    if os.environ.get("OPENROUTER_API_KEY"):
        tier2()
    else:
        print("\n== TIER 2 skipped: OPENROUTER_API_KEY is not set ==")
    print(f"\n{_N - len(_FAILURES)}/{_N} passed")
    if _FAILURES:
        print("\nFailures:")
        for name in _FAILURES:
            print(f"  - {name}")
    return 1 if _FAILURES else 0

if __name__ == "__main__":
    sys.exit(main())
