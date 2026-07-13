"""Streamlit adapter.

Presentation only, with one exception that is the whole architecture: the table of genes and
values is built from `skill_calls[-1].result`, not from the model's prose. The model writes the
sentences; pandas writes the numbers. "The model never computes a number" is therefore not a
claim about the prompt, it is a claim about this file -- there is no code path from a token the
model emitted to a digit on the screen.

Caveats are layered rather than dumped inline: a caveat attached to every number becomes wallpaper
and stops being read. Four layers, ordered by what a reader loses by skipping them:
  L0 the answer * L1 what we changed on you (always visible) * L2 how to read it (one click)
  * L3 the trace (one click).
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

import skills
from data import available_indications
from engine import NOT_IN_DATASET, REWRITE_NOTE, TRACE_NOTE, AnswerObject, ConfigurationError, answer

EXAMPLES = [
    "How can you help me?",
    "What are the main genes involved in lung cancer?",
    "What is the median value expression of genes involved in breast cancer?",
    "What is the median value expression of genes involved in esophageal cancer?",
]

st.set_page_config(page_title="K-mini", page_icon="🧬", layout="centered")


def render(a: AnswerObject) -> None:
    """Draw one answer. Every number here is read out of a skill result."""
    st.markdown(a.text)

    expressions = a.result("get_expressions")
    targets = a.result("get_targets")
    capabilities = a.result("describe_capabilities")

    # L0. Sorted by gene, never by value: an ordering is a claim, and without a unit these
    # genes are not on a common scale to be ranked on.
    if expressions and expressions.get("values"):
        frame = pd.DataFrame(
            sorted(expressions["values"].items()), columns=["Gene", "Median value"]
        )
        st.dataframe(
            frame,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Median value": st.column_config.NumberColumn(format="%.3f"),
            },
        )
    elif targets and targets.get("genes"):
        st.markdown(" ".join(f"`{g}`" for g in sorted(targets["genes"])))

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
    # reader is looking at a symbol that is not the one in the file, on our authority.
    for rewrite in a.rewrites():
        st.info(
            REWRITE_NOTE.format(frm=rewrite["from"], to=rewrite["to"]),
            icon=":material/sync_alt:",
        )

    # L2. Unconditional, so it is one click down: a caveat printed on every answer is chrome
    # within three answers, and teaches the reader that the grey text is skippable.
    if expressions and expressions.get("values"):
        with st.expander("How to read these numbers"):
            st.markdown(f"**The scale is unknown.** {skills.UNIT_NOTE}")
            if len(expressions["values"]) > 1:
                st.markdown(f"**Why {len(expressions['values'])} numbers and not one.** "
                            f"{skills.AGGREGATE_NOTE}")

    # L3. The integrity claim, and the label does the work: a closed expander marked "Trace"
    # tells a non-technical reader nothing.
    if a.skill_calls:
        n = len(a.skill_calls)
        with st.expander(f"How I got this — {n} skill call{'s' if n > 1 else ''}, "
                         f"0 numbers from the model"):
            for call in a.skill_calls:
                st.code(
                    f"{call.name}({json.dumps(call.arguments)})\n  -> "
                    f"{json.dumps(call.result, default=str)}",
                    language="json",
                )
            st.caption(TRACE_NOTE)
            st.caption(f"model `{a.model}` @ temperature 0 — routing only")


with st.sidebar:
    st.markdown("### K-mini")
    st.caption(
        "An agent over one table: the median value recorded for a (gene, cancer) pair. "
        "It routes your question to pandas and shows you every call it made."
    )
    st.markdown("**Try**")
    for example in EXAMPLES:
        if st.button(example, use_container_width=True):
            st.session_state.pending = example

st.title("K-mini")

if "history" not in st.session_state:
    st.session_state.history = []

for question, result in st.session_state.history:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        render(result) if isinstance(result, AnswerObject) else st.warning(result)

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
        render(result) if isinstance(result, AnswerObject) else st.warning(result)
    st.session_state.history.append((query, result))
