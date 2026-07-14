# K-mini

Ask about cancer genes in plain English. A language model picks **which** analysis to run; **pandas
runs it**. Every number on screen was computed by code, and the app shows you the call that produced
it.

The model routes and phrases. It never computes or chooses a number — and that is enforced in the
tool schema, not by asking it nicely. Section (a) says exactly where.

---

## Run it

**You need:** Docker, and an [OpenRouter API key](https://openrouter.ai/keys) (about a minute to
create — the app calls a hosted model, so it won't run without one). No GPU; all inference is remote.

**1.** Create a file called `.env` next to this README:

```
OPENROUTER_API_KEY=sk-or-...
```

**2.** Start it:

```bash
docker compose up
```

**3.** Open **http://localhost:8501** and ask a question.

That's the whole setup.

<details>
<summary><b>No Docker?</b> Python 3.11 works too.</summary>

Use **3.11** — `pandas` has no wheel for 3.14, which is the system `python3` on many machines.

```bash
python3.11 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py                     # same web app on :8501
python cli.py "What are the main genes involved in lung cancer?"   # or the terminal
```
</details>

## What to ask it

Four questions, and what it does with them:

**"How can you help me?"** — answers from a `describe_capabilities()` skill, so its stated abilities
are the ones it actually has, not the ones a model imagines a biostatistics tool should have. It is
as careful about what it *won't* do: *"Tell you a gene is not involved in a cancer. I can only say
this file holds no row for it — and the file is not a map of the biology."*

**"What are the main genes involved in lung cancer?"** — lists `ALK KRAS RET ROS1 STK11`, and
declines the ranking that *"main"* invites, because nothing in this file supports one.

**"What is the median value expression of genes involved in breast cancer?"** — the flagship. There
is no single median across genes, so it gives you the ten:

| Gene | Median value | | Gene | Median value |
|---|---:|---|---|---:|
| AKT1 | 0.278 | | ESR1 | 0.716 |
| BRCA1 | 0.094 | | GATA3 | 0.602 |
| BRCA2 | 0.032 | | MAP3K1 | 0.701 |
| CDH1 | 0.561 | | PIK3CA | 0.449 |
| ERBB2 | 0.420 | | TP53 | 0.233 |

Ordered by gene, never by value — an ordering is itself a claim. The refusal to collapse this to one
number is written in code (`skills.AGGREGATE_NOTE`); no aggregation function exists in the repo at
all. `ERBB2` is `HER2` in the source CSV — one gene, two names, disclosed on screen.

**"...involved in esophageal cancer?"** — esophageal is not in this dataset. It says so, invents no
numbers, and does not quietly answer about gastric instead.

## How it works

```
Streamlit / CLI  ->  engine.answer()  <->  OpenRouter (any tool-calling model)
                          |
                          v
                     skills.py (pandas)  ->  genes.py (HGNC)  ->  data.py -> CSV
```

The model reads the question, picks a skill and its arguments. The skill does the arithmetic in
pandas over an 81-row table and returns JSON. The model turns that JSON into a sentence. Every answer
carries the skill calls behind it, so you can check the number against the code instead of trusting
the model.

| File | Role |
|---|---|
| `engine.py` | agent loop, tool schemas, argument validation |
| `skills.py` | the four skills the model may call — **all computation lives here** |
| `genes.py` | HGNC symbol resolution (HER2 → ERBB2), with provenance |
| `indications.py` | cohort vocabulary: a term is a known cohort, or it is refused |
| `data.py` | data access — swapping the CSV for a database is confined to this module |
| `app.py` / `cli.py` | Streamlit and terminal adapters — presentation only |

## Tests

```bash
docker compose run --rm web python evals.py      # or: python evals.py
```

35 checks. **13 need no API key**: pandas assertions whose expected values are read from the CSV *at
test time* (see (b) for why that matters), plus a mutation test proving the suite would go red if the
data and the code drifted apart. The other **22 need the key**: they run the four questions above
end-to-end and assert that the right skill fired, that the genes and values returned are the CSV's
own, and that every number in the answer text traces back to a skill result.

## (a) The AI components, and the trade-offs

**One AI component**, and it has two jobs. A language model, reached over OpenRouter, runs a bounded
tool-calling loop in `engine.answer()` (`MAX_STEPS = 6`, so an unproductive model stops instead of
spinning). It **routes** — which skill, which arguments, in what order — and it **phrases** — turns
the returned JSON into a sentence a non-technical reader can follow. It never computes a value, ranks
one, or decides what a table contains.

**Why that's structural, not a policy.** The prompt does tell the model not to write numbers, but the
guarantee does not rest on it obeying. `app.py` and `cli.py` build the table from the recorded skill
result (`AnswerObject.result("get_expressions")`) and never parse a digit out of the model's prose.
There is no code path from a token the model emitted to a number on screen. If a model ignored the
prompt and narrated "0.5", that digit still would not reach the table — it would just be a sentence
sitting next to a table that disagreed with it.

**The schema is the enforcement, and its asymmetry is the design.** `get_expressions(genes,
cancer_name)` *requires* `cancer_name`, `enum`-constrained to the ten real cohorts. That is not
tidiness: `TP53` runs from 0.071 (gastric) to 0.972 (ovarian), so a call omitting the cohort must
pick one of eight rows on the caller's behalf — and picking is a scientific choice made by the wrong
party. An earlier version made it optional and broke the tie by CSV row order; the trace still looked
perfect, because a real skill returned a real number from a real row. Now the model cannot construct
that call at all.

`get_targets(cancer_name)` looks like it should carry the same enum and deliberately does not. Its
whole job is to take *any* wording — including "esophageal", which this file doesn't hold — and rule
on it in code. Constrain it and the model can no longer ask, so it answers from memory instead: a
guess with no trace, which is the thing this tool exists to prevent. So: **`enum` where a wrong value
would smuggle in a scientific claim; free text where the point is to let an unknown term reach a
skill that can refuse it.**

**Trade-off — a tool-calling loop, not a fixed pipeline.** The breast-cancer query needs chaining:
the arguments to `get_expressions` aren't known until `get_targets` has returned the gene list. So
the model, not hardcoded Python, decides the sequence. That buys a system that can answer a fifth
question nobody enumerated. The cost is a hard dependency on a hosted model whose tool-calling
reliability varies by provider — which is why every answer ships its trace instead of asking to be
trusted, and why `temperature=0` removes sampling noise rather than making the model a pure function.

**Trade-off — rigid skills, on purpose.** Every capability must be a named skill with a fixed schema.
There are four; a fifth query type means a fifth skill, not a cleverer prompt. For a chatbot that's a
limitation. For a tool whose worst failure is a confident wrong number, that rigidity is the feature.

## (b) Pros and cons of AI-assisted coding, in this case

Built with an AI assistant throughout. Every claim below points at something that actually happened
in this repository.

**Pro — scaffolding is fast, and that's real value.** The CLI, the Streamlit adapter, the Dockerfile,
the tool schemas and a first draft of the evals came out quickly and correctly.

**Con — a green test certified a bug.** An assistant-written eval asserted, under a function named
`ground_truth()`, that `get_expressions(["BRCA2"]) == 0.032`. BRCA2 appears three times in this CSV
(breast 0.032, pancreatic 0.112, prostate 0.379) and the call named no cohort, so it returned
whichever row loaded first. `0.032` encoded **CSV row order**, not biology — under the name "ground
truth." The suite pinned the very bug it existed to catch, and every run went green. The danger with
an AI assistant is not code that fails; it's code that *passes*.

**Con — fluent prose outran the code.** A design doc it wrote claimed the brief's functions were used
"verbatim… we do not rewrite their logic," while the code rewrote them. Nobody was lying: the
sentence was true of an earlier draft and never re-checked. Documentation is cheap to generate and
drifts by default, because there is no compiler for a paragraph.

**Con — it over-builds.** Unprompted, this repo grew to ~3,229 lines of Python and 2,089 of Markdown
before being cut back to roughly 1,500 and under 400. Left alone, it proposed: vendoring the
43,000-row HGNC table to disambiguate 54 symbols (a 12-entry alias map covers this dataset); an
ontology to resolve 10 cohort names; an across-gene aggregation skill (no such number exists); and a
vector store, for 81 rows that fit in a prompt many times over. Deciding what *not* to build is a
human call, every time.

**Pro — it is a tireless proofreader, and that's where it paid off most.** Cross-checking all 54 gene
symbols against HGNC nomenclature is exactly the mechanical work an assistant does without
complaining — and it is how the `HER2`/`ERBB2` collision below was found. Nobody catches that by
skimming an 81-row file. **The most valuable thing it produced here was a data finding, not a code
finding** — worth remembering when deciding where to point it.

**The discipline that makes it net-positive:** every claim it makes gets a test that can *fail*. Not
a test that passes — that's trivial to write, and it's exactly what produced the BRCA2 bug.

## What's wrong with the data

Three things in this file produce a false answer if you take it at face value. Two are defects, and
the code handles them. The third is a question only you can answer — and it blocks nothing the brief
asks for.

**`HER2` and `ERBB2` are the same gene** (HGNC:3430). The file records it as `HER2` in breast and
`ERBB2` in gastric. Keyed on the raw string those look like two different single-cohort genes — so
asking about ERBB2 in breast cancer returns *no data*: a false absence, for the trastuzumab target,
in the one cohort where trastuzumab is standard of care. `data.py` canonicalizes every symbol to its
HGNC-approved form at load and discloses the rewrite on screen.

**`EGFR` appears in zero rows** — not in lung, not anywhere. EGFR is among the most consequential
targets in lung cancer, so "EGFR is not involved in lung cancer" is not a harmless miss. It's false,
and it's exactly the kind of false a fluent model states with confidence. Absence from this file is a
fact *about the file*: every gene asked for comes back in `values` or in `not_found`, never dropped
by omission.

**`median_value` has no recorded unit** — nor sample size, dispersion, or baseline. This draws the
line the whole tool is built on:

- *Reporting needs no unit.* "This file records 0.094 for BRCA1 in breast" is true whatever 0.094
  measures. It's a quote, not a claim — so the tool reports freely.
- *Interpreting does.* "BRCA1 is higher than BRCA2" needs both genes on one scale. "The median across
  breast-cancer genes" needs an *n* and a spread per gene. Neither is recorded, so the tool refuses
  both — in code, not in a prompt.

And the file argues against the comfortable reading: all 81 values fall between 0.003 and 0.985. Raw
TPM is unbounded, so this isn't raw TPM — it has been normalized into a bounded range, and nothing
records against what. **So the question I'd ask you: what is `median_value` a median of, and was it
normalized within each cohort or across all of them?** If per-sample, TP53's 0.071 in gastric and
0.972 in ovarian are two measurements of one thing. If per-cohort — a percentile within each cancer's
own patients, which a bounded range makes plausible — they're positions in two different races.

Every question in the brief is answered without knowing. It gates only what a scientist asks *next* —
ranking, comparison, aggregation — all of which this tool currently, and correctly, refuses.

Full detail: [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | **required** |
| `OPENROUTER_MODEL` | `openai/gpt-4o-mini` | any tool-calling model |
| `OWKIN_DATA_PATH` | bundled CSV | point at a different dataset |
