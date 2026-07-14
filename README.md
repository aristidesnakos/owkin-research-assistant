# K-mini

Ask about cancer genes in plain English. A language model picks **which** analysis to run; **pandas
runs it**. Every number on screen was computed by code, and the app shows you the call that produced
it. The model routes and phrases — it never computes or chooses a number, and that is enforced in the
tool schema, not by asking it nicely.

## Run it

**You need** Docker and an [OpenRouter API key](https://openrouter.ai/keys) (a minute to create; the
app calls a hosted model, so it won't run without one). No GPU — all inference is remote.

1. Put your key in a file called `.env`, next to this README: `OPENROUTER_API_KEY=sk-or-...`
2. `docker compose up`
3. Open **http://localhost:8501**.

A query costs a fraction of a cent. It routes to `openai/gpt-5.6-luna` by default — the model this
was built and verified against — and any tool-calling model works: set `OPENROUTER_MODEL` to swap it.

**Where this has actually been run:** macOS (Apple Silicon), in Docker, which is how I verified it.
**I have not run it on Windows 11.** The brief asks for both, so I'd rather say that than imply a test
I didn't do. Nothing in it is platform-specific — one CPU-only container, remote inference, no GPU, no
native builds, no host paths — so I expect Docker Desktop on Windows to behave identically, but expect
is not verified, and on this repo that distinction is the whole point.

If you'd rather not create a key at all, `python evals.py` runs 13 checks against the CSV with no key
and no network (see [Tests](#tests)).

<details>
<summary><b>No Docker?</b> Python 3.11 works too.</summary>

Use **3.11** — `pandas` has no wheel for 3.14, the system `python3` on many machines.

```bash
python3.11 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py                                              # the web app, on :8501
python cli.py "What are the main genes involved in lung cancer?"  # or the terminal
```
</details>

---

# What I found in the data

I read the file before I wrote the app. Five things in it will produce a false answer if you take it
at face value. Four I could fix in code. The fifth is a question only you can answer — **and it
blocks nothing the brief asks for.**

### 1. `HER2` and `ERBB2` are the same gene

HGNC:3430 — recorded as `HER2` in the breast rows, `ERBB2` in the gastric rows. Keyed on the raw
string they look like two different single-cohort genes, so asking about ERBB2 in breast cancer
returns **no data**: a false absence, for the trastuzumab target, in the one cohort where trastuzumab
is standard of care.

**Fix:** `data.py` canonicalizes every symbol to its HGNC-approved form at load and discloses the
rewrite on screen. Had that merge collided inside a cohort, the loader raises rather than pick a
value by file order.

### 2. `EGFR` appears in zero rows — not in lung, not anywhere

EGFR is among the most consequential targets in lung cancer, so "EGFR is not involved in lung cancer"
is not a harmless miss. It's false, and it's exactly the kind of false a fluent model states with
confidence.

**Fix:** absence is a fact *about the file*. Every gene asked for comes back explicitly in `values`
or in `not_found`, never dropped by omission, and the tool only says *this file holds no row for it*
— never *this gene is not involved*.

### 3. "Involved in" is never defined

The CSV pairs a gene with a cancer and never says what the pairing **means**: recurrently mutated?
amplified? prognostic? therapeutically targeted? hand-curated? Each implies a different question the
data can answer — and the file's central verb is the one thing it doesn't document.

**Fix:** the tool says "the genes this dataset records for lung cancer", never "the genes that cause
lung cancer."

### 4. The cohorts are unstratified

Ten cancers, one undivided group each: no ER/PR status, no NSCLC/SCLC split, no stage, no date.

**Fix:** subtype questions are refused, not approximated. "ESR1 in TNBC" answered from the breast
cohort isn't a rough estimate — TNBC is ER-negative *by definition* while the cohort is unselected
and majority ER-positive, so the answer would be biased at exactly the gene asked about, in a
direction the reader can't see. `nsclc`, `sclc`, `tnbc`, `colon`, `rectal` and `skin` all resolve to
nothing, and an eval pins it.

That eval exists because the code once broke this rule while the paragraph above still claimed it:
`nsclc` quietly resolved to `lung` while `sclc` was refused — one subtype of an unstratified cohort
silently approximated, its sibling declined. A guarantee stated in prose is not a guarantee.

### 5. `median_value` has no recorded unit — and this is the question I'd ask you

No unit, no sample size, no dispersion, no baseline. That draws the line the tool is built on:

- **Reporting needs no unit.** "This file records 0.094 for BRCA1 in breast" is true whatever 0.094
  measures. It's a quote, not a claim — so the tool reports freely.
- **Interpreting does.** "BRCA1 is higher than BRCA2" needs both genes on one scale; "the median
  across breast-cancer genes" needs an *n* and a spread per gene. Neither is recorded, so the tool
  refuses both — in code (`skills.AGGREGATE_NOTE`), not in a prompt.

That this isn't pedantry: **I tried to sanity-check the values against known cancer biology and
could not — without the unit, I don't know what a "high" value would even predict.** There is no
external truth to check them against.

And the file argues against the comfortable reading: all 81 values fall between 0.003 and 0.985. Raw
TPM is unbounded, so this isn't raw TPM. It has been normalized into a bounded range, and nothing
records against what.

> **So: what is `median_value` a median of, and was it normalized within each cohort, or across all
> of them?**

Per-sample, TP53's 0.071 in gastric and 0.972 in ovarian are two measurements of one thing.
Per-cohort — a percentile within each cancer's own patients, which a bounded range makes plausible —
they're positions in two different races, and comparing them is meaningless.

**Not a blocker.** Every question in the brief is answered without knowing, and the app answers them.
The unit gates only what a scientist asks *next* — ranking, comparison, aggregation — all of which
the tool currently, and correctly, refuses.

Full detail: [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md).

---

## What it does

**"How can you help me?"** — answered from a `describe_capabilities()` skill, so its stated abilities
are the ones it actually has, not the ones a model imagines a biostatistics tool should have.

**"What are the main genes involved in lung cancer?"** — lists `ALK KRAS RET ROS1 STK11`, and
declines the ranking that *"main"* invites.

**"What is the median value expression of genes involved in breast cancer?"** — the flagship. No
single median across genes exists (finding 5), so it gives you the ten. Ordered by gene, never by
value: an ordering is itself a claim. `ERBB2` here is `HER2` in the CSV (finding 1), disclosed on
screen.

| Gene | Median value | | Gene | Median value |
|---|---:|---|---|---:|
| AKT1 | 0.278 | | ESR1 | 0.716 |
| BRCA1 | 0.094 | | GATA3 | 0.602 |
| BRCA2 | 0.032 | | MAP3K1 | 0.701 |
| CDH1 | 0.561 | | PIK3CA | 0.449 |
| ERBB2 | 0.420 | | TP53 | 0.233 |

**"...involved in esophageal cancer?"** — not in this dataset. It says so, invents no numbers, and
does not quietly answer about gastric instead.

## How it works

```
Streamlit / CLI  ->  engine.answer()  <->  OpenRouter (any tool-calling model)
                          |
                          v
                     skills.py (pandas)          all arithmetic happens here
                          |
                          +--  indications.py    a cohort we hold — or a refusal
                          +--  genes.py          HER2 -> ERBB2 (HGNC)
                          +--  data.py  ->  CSV
```

The model picks a skill and its arguments; the skill does the arithmetic in pandas and returns JSON;
the model turns that JSON into a sentence. Every answer carries the skill calls behind it, so you can
check the number against the code instead of trusting the model.

| File | Role |
|---|---|
| `engine.py` | agent loop, tool schemas, argument validation |
| `skills.py` | the four skills the model may call — **all computation lives here** |
| `genes.py` | HGNC symbol resolution (HER2 → ERBB2), with provenance |
| `indications.py` | cohort vocabulary: a term is a known cohort, or it is refused |
| `data.py` | data access — swapping the CSV for a database is confined to this module |
| `app.py` / `cli.py` | Streamlit and terminal adapters — presentation only |

### One note on the interface

The palette is Owkin's own, read from the `--owkin-colours--*` CSS variables on owkin.com rather than
eyeballed: beige `#faf4ed`, blue `#1439c1`, greige `#d6cdc7`, teal `#32c6c6`. It's plain Streamlit
theming (`.streamlit/config.toml` plus one CSS block) — no component library, no chat framework. A
chat framework's message renderer is exactly the layer that would tempt someone to render the table
from the model's prose, which is the one thing this design forbids.

The rule the styling obeys: **colour is structural, never data-encoding.** No median is shaded by its
magnitude, and no bar is drawn to its length. That's deliberate — a red-to-green ramp across these
values would assert exactly the "high vs low" reading the tool refuses in prose, and these genes
share no known scale to be ranked on (finding 5). Blue marks *disclosure* — a symbol we rewrote, a
call we made. The numbers stay black.

## (a) The AI components, and the trade-offs

**One AI component, two jobs.** A language model, over OpenRouter, runs a bounded tool-calling loop
in `engine.answer()` (`MAX_STEPS = 6`, so an unproductive model stops instead of spinning). It
**routes** — which skill, which arguments, in what order — and it **phrases**. It never computes a
value, ranks one, or decides what a table contains.

**Why that's structural, not a policy.** The prompt tells the model not to write numbers, but the
guarantee doesn't rest on it obeying. The adapters build the table from the recorded skill result
(`AnswerObject.result("get_expressions")`) and never parse a digit out of the model's prose. There is
no code path from a token the model emitted to a number on screen. If a model ignored the prompt and
narrated "0.5", that digit still wouldn't reach the table — it'd be a sentence sitting next to a
table that disagreed with it.

**The schema is the enforcement, and its asymmetry is the design.** `get_expressions(genes,
cancer_name)` *requires* `cancer_name`, `enum`-constrained to the ten real cohorts. Not tidiness:
`TP53` runs 0.071 (gastric) to 0.972 (ovarian), so a call omitting the cohort must pick one of eight
rows on the caller's behalf — and picking is a scientific choice made by the wrong party. An earlier
version made it optional and broke the tie by CSV row order; the trace still looked perfect, because
a real skill returned a real number from a real row. Now the model cannot construct that call at all.

`get_targets(cancer_name)` looks like it needs the same enum and deliberately doesn't. Its whole job
is to take *any* wording — including "esophageal", which this file doesn't hold — and rule on it in
code. Constrain it and the model can't ask, so it answers from memory instead: a guess with no trace,
the exact thing this tool exists to prevent. So: **`enum` where a wrong value would smuggle in a
scientific claim; free text where the point is to let an unknown term reach a skill that refuses it.**

**Trade-off — a tool-calling loop, not a fixed pipeline.** The breast query needs chaining: the
arguments to `get_expressions` aren't known until `get_targets` returns the gene list. So the model,
not hardcoded Python, decides the sequence. That buys a system that can answer a fifth question
nobody enumerated. The cost is a hard dependency on a hosted model whose tool-calling reliability
varies by provider — which is why every answer ships its trace instead of asking to be trusted.

**Trade-off — rigid skills, on purpose.** Every capability is a named skill with a fixed schema.
There are four; a fifth query type means a fifth skill, not a cleverer prompt. For a chatbot that's a
limitation. For a tool whose worst failure is a confident wrong number, it's the feature.

## (b) Pros and cons of AI-assisted coding, in this case

Built with an AI assistant throughout. Every claim below points at something that happened here.

**Pro — scaffolding is fast, and that's real value.** The CLI, the Streamlit adapter, the Dockerfile,
the tool schemas and a first draft of the evals came out quickly and correctly.

**Con — a green test certified a bug.** An assistant-written eval asserted, under a function named
`ground_truth()`, that `get_expressions(["BRCA2"]) == 0.032`. BRCA2 appears three times in this CSV
(breast 0.032, pancreatic 0.112, prostate 0.379) and the call named no cohort, so it returned
whichever row loaded first. `0.032` encoded **CSV row order**, not biology — under the name "ground
truth." The suite pinned the very bug it existed to catch, and every run went green. The danger with
an AI assistant isn't code that fails; it's code that *passes*.

**Con — fluent prose outran the code.** A design doc it wrote claimed the brief's functions were used
"verbatim… we do not rewrite their logic," while the code rewrote them. Nobody was lying: the
sentence was true of an earlier draft and never re-checked. Documentation is cheap to generate and
drifts by default, because there is no compiler for a paragraph.

**Con — it over-builds.** Unprompted, this repo grew to ~3,229 lines of Python before being cut back
to roughly 1,500. Left alone it proposed: vendoring the 43,000-row HGNC table to disambiguate 54
symbols (a 12-entry alias map covers this dataset); an ontology to resolve 10 cohort names; an
across-gene aggregation skill (no such number exists); and a vector store, for 81 rows that fit in a
prompt many times over.

**Pro — a tireless proofreader, and that's where it paid off most.** Cross-checking all 54 gene
symbols against HGNC nomenclature is exactly the mechanical work an assistant does without
complaining — and it's how finding 1 surfaced. Nobody catches that by skimming an 81-row file.
**The most valuable thing it produced was a data finding, not a code finding** — worth remembering
when deciding where to point it.

**The discipline that makes it net-positive:** every claim it makes gets a test that can *fail*. Not
a test that passes — that's trivial to write, and it's exactly what produced the BRCA2 bug.

## Tests

```bash
docker compose run --rm web python evals.py      # or: python evals.py
```

36 checks, and the Docker command is the one to trust: it runs them in the artifact you actually
ship, which is not the same thing as your laptop (that command used to fail, for a reason worth
reading — see below).

**14 need no API key.** Mostly pandas assertions whose expected values are read from the CSV *at test
time*, never hardcoded (see (b) — a hardcoded one is what certified the BRCA2 bug). Plus four that
guard the seams rather than the arithmetic: every tool schema's parameters match its function's
signature, `docs/DATA_DICTIONARY.md` quotes `skills.UNIT_NOTE` verbatim, no subtype resolves to the
cohort that contains it, and a **mutation test** that edits a value in a copy of the CSV and asserts
the suite notices — proof that these tests can go red.

**The other 22 need the key.** They run the four questions end-to-end and assert the right skill
fired, that the genes and values returned are the CSV's own, and that every number in the answer text
traces back to a skill result.

**Run them in Docker.** `docs/DATA_DICTIONARY.md` was excluded from the image, so the check that pins
that doc to the code passed on the laptop and failed in the image — green where it didn't matter, red
where it did. Nobody had run the suite inside the container. The deliverable is the image, not the
working tree, and they drift apart in silence.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | **required** |
| `OPENROUTER_MODEL` | `openai/gpt-5.6-luna` | any tool-calling model |
| `OWKIN_DATA_PATH` | bundled CSV | point at a different dataset |
