# K-mini — an agentic research assistant for biological data

Ask a question about cancer genes in plain English. A language model decides **which** analysis to
run; **pandas runs it**. Every number you see was computed by deterministic code, and the trace
shows you exactly which code produced it.

The model routes and phrases. The model never computes or selects a number. That is the whole
design, and section (a) below explains exactly where that is enforced — in the tool schema, not in
a prompt asking nicely.

## Run it

You need an **OpenRouter API key** (the app is a thin client over a hosted model, so it will not
run without one). Getting one takes about 90 seconds at
[openrouter.ai/keys](https://openrouter.ai/keys) — sign in, create a key, paste it in below.

Create a file called `.env` next to this README, with your key in it:

```bash
OPENROUTER_API_KEY=sk-or-...        # required
OPENROUTER_MODEL=openai/gpt-4o-mini # optional; any tool-calling model on OpenRouter
```

Then:

```bash
docker compose up           # web app on http://localhost:8501
```

Runs on macOS (Apple Silicon or Intel) and Windows 11, ≤16 GB RAM, no GPU — all inference is
remote, so nothing heavy runs on your machine.

Prefer the terminal, or don't want Docker? **Use Python 3.11** — the pins match the container's
`python:3.11-slim`, and `pandas==3.0.3` has no wheel for 3.14, which is the system `python3` on
many machines.

```bash
python3.11 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python cli.py "What are the main genes involved in lung cancer?"
python cli.py                                   # interactive REPL

# or, inside the container:
docker compose run --rm web python cli.py "What are the main genes involved in lung cancer?"
```

### Run the tests

```bash
python evals.py     # or: docker compose run --rm web python evals.py
```

**Tier 1 needs no API key and no network** (13 checks): deterministic assertions on `skills.py`,
with every expected value derived from the CSV *at test time* — see (b) for why that matters — plus
a mutation test proving the suite would go red if the data and the implementation drifted apart,
a check that every tool schema matches the signature of the function it dispatches to, and a check
that `docs/DATA_DICTIONARY.md` still quotes the live `UNIT_NOTE`.
**Tier 2** runs only if `OPENROUTER_API_KEY` is set (22 more, 35 in total): the four canonical
queries end to end, asserting the right skill fired with the right arguments, that every skill call
returned a usable result, that the genes and values it returned are the CSV's own, and that every
number in the answer text traces back to a skill result.

## How it works

```
CLI / Streamlit  ->  engine.answer()  <->  OpenRouter (any tool-calling model)
                          |
                          v
                     skills.py (pandas)  ->  genes.py (HGNC)  ->  data.py -> CSV
```

The model reads the question and picks a **skill** plus arguments. The skills do the arithmetic in
pandas over an 81-row frame and hand back JSON. The model turns that JSON into prose. Every answer
carries the skill calls that produced it, so you can check the number against the code rather than
trusting the model.

| File | Role |
|---|---|
| `engine.py` | the agent loop, tool schemas, argument validation |
| `skills.py` | the skills the model may call — all computation lives here |
| `genes.py` | HGNC symbol resolution (HER2 -> ERBB2), with provenance |
| `indications.py` | cohort vocabulary: a term is a known cohort, or it is refused |
| `data.py` | data access (CSV today; swapping the store is confined to this module) |
| `cli.py` / `app.py` | thin terminal / Streamlit adapters — presentation only |

## The four canonical queries

Verbatim from `python cli.py "<query>"` on one run, traces abridged (the app prints them in full).
The model's prose is generated, so its wording will vary between runs; every **gene and number
below is rendered by the adapter from the skill result**, so those do not vary.

**1. "How can you help me?"** — answered from a `describe_capabilities()` skill result, so the
tool's stated abilities are the ones it actually has, not the ones a model imagines a
biostatistics tool should have. It reports what it *cannot* do as carefully as what it can.

> I can list the genes recorded for a cancer, report a gene's recorded median for a specific
> cancer, and show one gene's values across cancers. I can also resolve aliases such as HER2 to
> ERBB2 and identify when a cancer or gene has no row in this dataset.

...above a code-authored capability list (`I CAN` / `I WILL NOT`), of which the load-bearing entry
is: *"Tell you a gene is not involved in a cancer. I can only say this file holds no row for it —
and the file is not a map of the biology."*

**2. "What are the main genes involved in lung cancer?"** — note what it does with *"main"*: it
declines the ranking the word invites, because nothing in this file supports one.

> The dataset lists the genes recorded for lung cancer below. This is a dataset listing, not a
> statement about biological importance.
>
> ```
>   ALK  KRAS  RET  ROS1  STK11
> ```

**3. "What is the median value expression of genes involved in breast cancer?"**

> The dataset's per-gene median values for the breast cancer cohort are shown in the table. There
> is no single meaningful median across all genes; the dataset does not record the information
> needed to calculate one.

| Gene | Median value | | Gene | Median value |
|---|---:|---|---|---:|
| AKT1 | 0.278 | | ESR1 | 0.716 |
| BRCA1 | 0.094 | | GATA3 | 0.602 |
| BRCA2 | 0.032 | | MAP3K1 | 0.701 |
| CDH1 | 0.561 | | PIK3CA | 0.449 |
| ERBB2 | 0.420 | | TP53 | 0.233 |

Ordered by gene, never by value — an ordering is itself a claim, and without a unit these genes are
not on a common scale to be ranked on. The refusal to produce one number is **code-authored**
(`skills.AGGREGATE_NOTE`), not model improv, and no aggregation function exists anywhere in the
repo to produce the number it declines to give. `ERBB2` here is `HER2` in the source CSV — one gene
under two identifiers, disclosed on screen; the full story is in
[`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md).

**4. "What is the median value expression of genes involved in esophageal cancer?"** — esophageal
is **not** in this dataset.

> This dataset has no rows for esophageal cancer. That is a gap in this dataset, not a conclusion
> about the cancer itself.

It invents no numbers and does not quietly answer about gastric instead. The refusal is
**code-authored, not schema-enforced**, and that distinction is the interesting one:
`get_targets` accepts free text (`engine._TERM_PARAM`), so "esophageal cancer" *does* reach the
skill — `indications.resolve` then finds no cohort and the skill returns `status:
unknown_indication` with the ten real cohorts attached. The tool refuses on its own authority and
says what it does hold. `get_expressions`, by contrast, *is* enum-constrained, so no arbitrary
cohort can ever be selected for a value lookup. Why the two differ is in (a) below.

## (a) Architecture, use, and trade-offs of the AI components

**What the model is for.** There is exactly one AI component: a language model, reached over
OpenRouter, running a bounded tool-calling loop in `engine.answer()` (`MAX_STEPS = 6`, so an
unproductive model terminates instead of spinning). It does two jobs, and only two: it **routes**
— decides which skill to call, with which arguments, in which order — and it **phrases** — turns a
returned JSON result into one or two sentences a non-technical reader can follow. It never
computes a value, ranks one, or decides what a table contains.

**Why that's structural, not a policy.** The prompt does tell the model not to write numbers. But
the guarantee doesn't rest on the model obeying that instruction: `app.py` and `cli.py` build the
results table directly from the last `get_expressions` result (`AnswerObject.result()`, which scans
the recorded skill calls backwards by name) — and never parse a number out of the model's own
sentences. There is no code path from a
token the model emitted to a digit on screen. If a model ever ignored the prompt and narrated
"0.5" in its prose, that digit still would not reach the table; it would just be a sentence sitting
next to a table that disagreed with it.

**Why OpenRouter.** The model is one environment variable (`OPENROUTER_MODEL`) — swap it, no code
change, which matters for a prototype whose model choice shouldn't be load-bearing. The trade-off
is a hard external dependency (no key, no app) and the fact that tool-calling reliability — whether
a model emits well-formed function calls at all — varies by provider and model, which is exactly
why the schemas below carry so much of the weight, and why `temperature=0` is described here as
removing sampling noise, not as making a hosted model a pure function.

**Why the guarantees live in the schema, not the prompt.** `get_expressions(genes, cancer_name)`
requires `cancer_name`, and `cancer_name` is `enum`-constrained to the ten cohorts this dataset
actually holds. That isn't a style choice: `TP53` alone ranges from 0.071 (gastric) to 0.972
(ovarian) across eight cohorts, so a call that omitted the cohort would have to pick one of eight
rows on the caller's behalf — and picking is a scientific choice made by the wrong party. An
earlier version made the argument optional and resolved the ambiguity with `keep="first"`, i.e. by
CSV row order; the trace still looked perfect, because a real skill returned a real number from a
real row. Making the argument required and enum-constrained means the model cannot construct that
call at all — it isn't asked not to, it has no way to. A guarantee enforced by a prompt is a
request; a guarantee enforced by a schema is a fact about which calls exist.

`get_targets(cancer_name)` looks like it should carry the same enum, and deliberately does not.
Its argument is free text, because that skill's entire job is to take *any* wording the user
typed — including one this dataset doesn't hold, like "esophageal" — and rule on it in code: say
yes and list the genes, or say no and list what cohorts exist. Constrain that argument and the
model could no longer pass an out-of-vocabulary term at all, so it would answer "is esophageal in
this dataset?" from memory instead of from the resolver — precisely the guess-with-no-trace this
tool exists to prevent. The asymmetry is the design: `enum` where a wrong value could silently
smuggle in a scientific claim, free text where the point is to let an unrecognized value reach a
skill that can refuse it on its own authority.

**Trade-off: a tool-calling loop, not a hardcoded pipeline.** The headline query needs chaining —
the arguments to `get_expressions` aren't known until `get_targets` has returned the gene list —
so the model, not fixed Python, decides the sequence. That buys a system that can answer a fifth
question we didn't enumerate; the cost is the reliability caveat above, which is why every answer
ships its trace instead of asking to be trusted.

**Trade-off: deterministic skills are rigid, on purpose.** Every capability this tool has must be
registered as a named skill with a fixed schema — there are four, and adding a fifth query type
means writing a fifth skill, not a cleverer prompt. For a general chatbot that's a limitation. For
a tool whose worst failure mode is a wrong number with a clean audit trail, that rigidity is the
feature: the system can only do what has been explicitly built, tested, and can be pointed at in a
review.

## (b) Pros and cons of AI-assisted coding, in this case

Built with an AI coding assistant throughout, and the honest account is more useful to a reviewer
than a polished one. Every claim below points at something that actually happened in this
repository.

**Pro: scaffolding is fast, and that's real value.** The CLI, the Streamlit adapter, the
Dockerfile, the tool schemas, and a first draft of the eval cases all came out of the assistant
quickly and correctly. It is also good at drafting trade-off prose like this section — a first
pass that a human then has to check line by line against the code, which is the point of the next
paragraph.

**Con, the load-bearing anecdote: a green test certified a bug.** An earlier assistant-written
eval suite contained, under a function named `ground_truth()`, an assertion equivalent to
`get_expressions(["BRCA2"]) == 0.032`. `BRCA2` appears in this CSV three times — breast 0.032,
pancreatic 0.112, prostate 0.379 — and the call passed no indication, so it returned whichever row
happened to load first. `0.032` encoded **CSV row order**, not biology, and it encoded that under
the name "ground truth." The test suite pinned the very bug it existed to catch, and every run went
green. That is the risk in one sentence: the danger with an AI assistant is not code that fails,
it's code that *passes* — plus a confidently-named test saying so.

**Con: fluent prose outran the implementation.** A design document the assistant wrote claimed the
two functions provided in the brief were used "verbatim… we do not rewrite their logic," while the
code did rewrite them — see the `get_expressions` schema change in (a) above. Nobody involved was
lying; the sentence was true of an earlier draft and was never re-checked against the code that
superseded it. AI makes documentation cheap to produce, and cheap documentation drifts by default,
because there is no compiler for a paragraph.

**Con: it over-builds by default.** Unprompted, this repo grew to roughly 3,229 lines of Python
(from a ~470-line starting point) and 2,089 lines of Markdown, before being cut back to about 1,500
and well under 400 respectively — this document included. Left alone, an assistant proposed, among
other things: vendoring the 43,000-row HGNC table to disambiguate 54 gene symbols (a 12-entry alias
table covers what this dataset needs); an OncoTree/NCIt ontology to resolve 10 cohort names; an
across-gene aggregation skill (medians don't compose across genes — no such number exists to
compute); and RAG or a vector store, for 81 rows that fit in a prompt many times over. It supplies
volume by default. Deciding what *not* to build is a human call, every time — and it is what this
brief says it is grading.

**Pro, but a narrow one: it is a fast, tireless proofreader.** Cross-checking all 54 gene symbols
in this CSV against HGNC nomenclature is exactly the kind of mechanical check an assistant will do
without complaint, and it is how the `HER2`/`ERBB2` data collision documented in
[`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md) was found. Nobody skimming an 81-row file by
eye catches that reliably; a tool that never gets bored will. The highest-value thing the assistant
contributed here was a **data** finding, not a code finding — worth remembering when deciding where
to point it.

**The discipline that makes it net-positive.** Every claim the assistant makes gets a test that can
fail — not a test that passes, which is trivial to write and is exactly what produced the BRCA2 bug
above. Verification, not typing speed, is where the human judgment in this project actually lives.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | **required** |
| `OPENROUTER_MODEL` | `openai/gpt-4o-mini` | any tool-calling-capable model |
| `OWKIN_DATA_PATH` | bundled CSV | point at a different dataset |

## The data

`median_value` carries no recorded unit, sample size, dispersion, or baseline — which is why the
tool reports values but never ranks, compares, or characterizes them. Full data dictionary,
including the `HER2`/`ERBB2` identity and what "involved in" does and doesn't mean here:
[`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md).
