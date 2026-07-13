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

```bash
cp .env.example .env        # Windows: copy .env.example .env
# open .env and paste your key into OPENROUTER_API_KEY

docker compose up           # web app on http://localhost:8501
```

Runs on macOS (Apple Silicon or Intel) and Windows 11, ≤16 GB RAM, no GPU — all inference is
remote, so nothing heavy runs on your machine.

Prefer the terminal, or don't want Docker?

```bash
pip install -r requirements.txt
python cli.py "What are the main genes involved in lung cancer?"
python cli.py                                   # interactive REPL

# or, inside the container:
docker compose run --rm web python cli.py "What are the main genes involved in lung cancer?"
```

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

Real output, lightly abridged (traces trimmed; the app prints them in full).

**1. "How can you help me?"** — answered from a `describe_capabilities()` skill result, so the
tool's stated abilities are the ones it actually has, not the ones a model imagines a
biostatistics tool should have. It reports what it *cannot* do as carefully as what it can.

> I can list the genes recorded for an indication; report a gene's recorded median value within
> one indication; show a gene's values across every indication where it appears; resolve aliases
> to approved symbols — for example, **HER2 → ERBB2** — and tell you when I do.
>
> It does **not** record units, sample sizes, dispersion, baselines, or sample-level data.
> Therefore I cannot infer whether a value is high or low, compare groups, calculate cross-gene
> aggregates, or draw statistical or therapeutic conclusions.

**2. "What are the main genes involved in lung cancer?"**

> For **lung cancer**, this dataset contains rows for these genes: ALK, RET, ROS1, STK11, KRAS.
>
> These are genes present in the dataset for the lung cohort, not necessarily validated
> therapeutic targets or a complete list of genes involved in lung cancer.
>
> ```
> get_targets({"cancer_name": "lung cancer"})
>   -> {"status": "ok", "cancer": "lung", "genes": ["ALK", "RET", "ROS1", "STK11", "KRAS"], ...}
> ```

**3. "What is the median value expression of genes involved in breast cancer?"**

> | Gene | Median value | | Gene | Median value |
> |---|---:|---|---|---:|
> | BRCA2 | 0.032 | | ESR1 | 0.716 |
> | BRCA1 | 0.094 | | MAP3K1 | 0.701 |
> | TP53 | 0.233 | | ERBB2 | 0.42 |
> | GATA3 | 0.602 | | PIK3CA | 0.449 |
> | CDH1 | 0.561 | | AKT1 | 0.278 |
>
> **Interpretation note:** This question has two readings and only one is well-posed. The answer
> given is the per-gene table. The other reading — a single median across the 10 genes — is not
> computed, and no skill here will compute it. It would be a median of medians: it aggregates over
> genes rather than samples, and medians do not compose […]

That note is **code-authored**, not model improv, and no aggregation function exists anywhere in
the repo to produce the number it declines to give. (`ERBB2` here is `HER2` in the source CSV —
one gene under two identifiers; the full story is in
[`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md).)

**4. "What is the median value expression of genes involved in esophageal cancer?"** — esophageal
is **not** in this dataset.

> Esophageal cancer is not an indication in this dataset. The available cohorts are: breast,
> colorectal, gastric, glioblastoma, lung, melanoma, ovarian, pancreatic, prostate, and renal.

It invents no numbers and does not quietly answer about gastric instead. The tool schema's
`cancer_name` is an `enum` generated from the CSV, so "esophageal" is not a call the model can
make in the first place — more on why in (a) below.

## (a) Architecture, use, and trade-offs of the AI components

**What the model is for.** There is exactly one AI component: a language model, reached over
OpenRouter, running a bounded tool-calling loop in `engine.answer()` (`MAX_STEPS = 6`, so an
unproductive model terminates instead of spinning). It does two jobs, and only two: it **routes**
— decides which skill to call, with which arguments, in which order — and it **phrases** — turns a
returned JSON result into one or two sentences a non-technical reader can follow. It never
computes a value, ranks one, or decides what a table contains.

**Why that's structural, not a policy.** The prompt does tell the model not to write numbers. But
the guarantee doesn't rest on the model obeying that instruction: `app.py` and `cli.py` build the
results table directly from `skill_calls[-1].result` — the return value of the last skill actually
called — and never parse a number out of the model's own sentences. There is no code path from a
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
(from a ~470-line starting point) and 2,089 lines of Markdown, before being cut back to about 1,280
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
