"""Streamlit adapter.

Presentation only, with one exception that is the whole architecture: the table of genes and
values is built from the recorded skill result (`a.result("get_expressions")`), not from the
model's prose. The model writes the sentences; pandas writes the numbers. "The model never
computes a number" is therefore not a claim about the prompt, it is a claim about this file --
there is no code path from a token the model emitted to a digit on the screen.

Caveats are layered rather than dumped inline: a caveat attached to every number becomes wallpaper
and stops being read. Four layers, ordered by what a reader loses by skipping them:
  L0 the answer * L1 what we changed on you (always visible) * L2 how to read it (one click)
  * L3 the provenance (one click).

The styling here is deliberately thin -- sizes, rules and spacing, almost no colour. Streamlit's
own theme supplies the palette, so this file cannot go blind in a light terminal or a dark one.
"""
from __future__ import annotations

import html
import json

import streamlit as st

import skills
from data import available_indications
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

EXAMPLES = [
    "How can you help me?",
    "What are the main genes involved in lung cancer?",
    "What is the median value expression of genes involved in breast cancer?",
    "What is the median value expression of genes involved in esophageal cancer?",
]

st.set_page_config(page_title="K-mini", page_icon="🧬", layout="centered")

# Sizes, rules and spacing only. Colour comes from Streamlit's theme (currentColor and a neutral
# grey at low alpha), so nothing here assumes a dark background.
st.markdown(
    """
    <style>
      .block-container { max-width: 46rem; padding-top: 3.5rem; padding-bottom: 7rem; }

      /* The answer is prose, and prose is meant to be read, not scanned. The assistant's own
         first paragraph is the lede and carries the answer, so it is set largest. Sized here
         rather than by wrapping the text in a styled element, because the model's prose has to
         stay markdown -- see render(). */
      .stChatMessage .stMarkdown p, .stChatMessage .stMarkdown li {
          font-size: 1.05rem; line-height: 1.7;
      }
      .stChatMessage .stMarkdown p:first-child { font-size: 1.18rem; line-height: 1.6; }
      .k-lede { font-size: 1.18rem; line-height: 1.65; margin: .1rem 0 1.25rem; }

      /* The value table. A report, not a spreadsheet widget: no sort handles, no index
         gutter, no scrollbar -- ten rows do not need infrastructure. */
      .k-table { width: 100%; border-collapse: collapse; margin: .25rem 0 1.25rem; }
      /* opacity .75, not .55: at .55 this washed out to 3.22:1 on Streamlit's light theme, under
         the 4.5:1 WCAG AA floor for text this small. Dark theme was always fine; light was not. */
      .k-table th {
          text-align: left; font-size: .75rem; font-weight: 600; letter-spacing: .09em;
          text-transform: uppercase; opacity: .75; padding: 0 0 .6rem;
          border-bottom: 1px solid rgba(128,128,128,.28);
      }
      .k-table td {
          padding: .6rem 0; border-bottom: 1px solid rgba(128,128,128,.14); font-size: 1.02rem;
      }
      .k-table tr:last-child td { border-bottom: none; }
      .k-gene { font-weight: 600; letter-spacing: .01em; }
      /* Tabular figures, so digits share a width and the decimal points align. Legibility only --
         NOT an invitation to read down the column: these genes share no known scale, which is why
         _table() sorts by name. Alignment is not ranking. */
      .k-num {
          text-align: right; font-variant-numeric: tabular-nums;
          font-feature-settings: "tnum"; font-size: 1.05rem;
      }

      .k-chips { font-size: .95rem; line-height: 2.1; }

      /* Provenance. The claim is that the numbers were computed, so it is set like a citation:
         a rule, a monospace call, an indented result. Not a JSON dump the reader skips. */
      .k-prov {
          border-left: 2px solid rgba(128,128,128,.35); padding: .15rem 0 .15rem .95rem;
          margin: .1rem 0 .9rem;
      }
      .k-call {
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .86rem;
          line-height: 1.55; word-break: break-word;
      }
      .k-call .k-skill { font-weight: 700; }
      .k-ret { opacity: .68; padding-left: 1.1rem; display: block; margin-top: .2rem; }
      .k-seal {
          font-size: .82rem; opacity: .72; line-height: 1.6;
          border-top: 1px solid rgba(128,128,128,.2); padding-top: .7rem; margin-top: .3rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def _table(values: dict) -> str:
    """The gene/value table, built from a skill result. Sorted by gene, never by value: an
    ordering is a claim, and without a unit these genes are not on a common scale to be ranked on.

    Escaped, though every symbol here came out of our own CSV -- a renderer that trusts its input
    because of where the input came from is one data source away from being wrong.
    """
    rows = "".join(
        f'<tr><td class="k-gene">{html.escape(str(gene))}</td>'
        f'<td class="k-num">{value:.3f}</td></tr>'
        for gene, value in sorted(values.items())
    )
    return (
        '<table class="k-table"><thead><tr><th>Gene</th>'
        '<th class="k-num">Median value</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def render(a: AnswerObject) -> None:
    """Draw one answer. Every number here is read out of a skill result."""
    # Rendered as markdown, NOT escaped into a <p>. The model's prose is the one thing here it is
    # allowed to author, and any tool-calling model on OpenRouter may emit bold, or a list, or two
    # paragraphs. Escaping it into a single element printed the asterisks and -- on a blank line --
    # closed the block early and spilled a stray </p> into the page. Sizing is done in CSS instead.
    st.markdown(a.text or "")

    expressions = a.result("get_expressions")
    targets = a.result("get_targets")
    capabilities = a.result("describe_capabilities")

    # L0. The numbers, straight from pandas.
    if expressions and expressions.get("values"):
        st.markdown(_table(expressions["values"]), unsafe_allow_html=True)
    elif targets and targets.get("genes"):
        st.markdown(
            '<p class="k-chips">'
            + "  ".join(f"<code>{html.escape(g)}</code>" for g in sorted(targets["genes"]))
            + "</p>",
            unsafe_allow_html=True,
        )

    if capabilities:
        st.caption(capabilities["dataset"])
        left, right = st.columns(2)
        left.markdown("**What I can do**\n\n" + "\n".join(f"- {x}" for x in capabilities["i_can"]))
        right.markdown(
            "**What I will not do**\n\n" + "\n".join(f"- {x}" for x in capabilities["i_cannot"])
        )

    # L0 again: a refusal is an answer, so it wears the answer's clothes. Not st.error -- red
    # says the software broke, and a stakeholder who sees red files a bug instead of reading
    # the sentence. The software worked; it told them a true thing about the file.
    for result in (expressions, targets):
        if result and result.get("status") == "unknown_indication":
            st.info(NOT_IN_DATASET.format(cancer=result["cancer"]), icon=":material/info:")
            st.markdown("**The indications I do have:** " + " ".join(
                f"`{i}`" for i in result.get("available", available_indications())
            ))
            break

    # L1. Conditional, so it is a signal rather than wallpaper -- and unmissable, because the
    # reader is looking at a symbol that is not the one in the file, on our authority. The gloss
    # (what the gene is) leads; the disclosure (what we renamed) follows.
    for rewrite in a.rewrites():
        lead = REWRITE_GLOSS.get(rewrite["to"]) or REWRITE_IDENTITY.format(
            frm=rewrite["from"], to=rewrite["to"]
        )
        note = REWRITE_NOTE.format(frm=rewrite["from"], to=rewrite["to"])
        st.info(f"{lead}\n\n{note}", icon=":material/sync_alt:")

    # L2. Unconditional, so it is one click down: a caveat printed on every answer is chrome
    # within three answers, and teaches the reader that the grey text is skippable.
    if expressions and expressions.get("values"):
        with st.expander("How to read these numbers"):
            st.markdown(f"**The scale is unknown.** {skills.UNIT_NOTE}")
            if len(expressions["values"]) > 1:
                st.markdown(f"**Why {len(expressions['values'])} numbers and not one.** "
                            f"{skills.AGGREGATE_NOTE}")

    # L3. The integrity claim. The label does the work -- a closed expander marked "Trace" tells a
    # non-technical reader nothing, so it states the count and the zero.
    if a.skill_calls:
        n = len(a.skill_calls)
        with st.expander(
            f"Provenance — {n} skill call{'s' if n > 1 else ''}, 0 numbers from the model"
        ):
            for call in a.skill_calls:
                args = ", ".join(f"{k}={json.dumps(v)}" for k, v in (call.arguments or {}).items())
                result = json.dumps(call.result, default=str)
                st.markdown(
                    '<div class="k-prov"><div class="k-call">'
                    f'<span class="k-skill">{html.escape(call.name)}</span>'
                    f"({html.escape(args)})"
                    f'<span class="k-ret">→ {html.escape(result)}</span>'
                    "</div></div>",
                    unsafe_allow_html=True,
                )
            st.markdown(
                f'<div class="k-seal">{html.escape(TRACE_NOTE)}<br>'
                f"Model <code>{html.escape(a.model)}</code> at temperature 0 — routing only."
                "</div>",
                unsafe_allow_html=True,
            )


def show(result: object) -> None:
    """A statement, deliberately, not a conditional expression. Streamlit's "magic" auto-renders
    any bare top-level expression, so `render(x) if cond else st.warning(x)` written as a statement
    displayed `render`'s return value -- a literal green "None" badge under every single answer.
    """
    if isinstance(result, AnswerObject):
        render(result)
    else:
        st.warning(result)


with st.sidebar:
    st.markdown("### K-mini")
    st.caption(
        "An agent over one table: the median value recorded for a (gene, cancer) pair. "
        "It routes your question to pandas and shows you every call it made."
    )
    st.caption(
        "Ask in your own words. The examples below are only a starting point -- anything about "
        f"these {len(available_indications())} cohorts works."
    )

if "history" not in st.session_state:
    st.session_state.history = []

st.title("K-mini")

# The empty state does the teaching. The question box is the product, so it is what a first-time
# reader meets -- the examples sit under it as one-click seeds, not as the way in.
if not st.session_state.history:
    st.markdown(
        '<p class="k-lede">Ask about the genes and median values recorded for a cancer '
        "cohort — in your own words.</p>",
        unsafe_allow_html=True,
    )
    st.caption("Or start from one of these:")
    for example in EXAMPLES:
        if st.button(example, use_container_width=True):
            st.session_state.pending = example

for question, result in st.session_state.history:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        show(result)

query = st.chat_input("Ask about a cancer indication...") or st.session_state.pop("pending", None)

if query:
    with st.chat_message("user"):
        st.markdown(query)
    with st.chat_message("assistant"):
        with st.spinner("Routing to skills..."):
            try:
                result = answer(query)
            except ConfigurationError as exc:
                result = str(exc)
        show(result)
    st.session_state.history.append((query, result))
    # The examples were part of the empty state; once there is history, the page owes the reader
    # the conversation instead. Rerun so they disappear rather than lingering under the answer.
    st.rerun()
