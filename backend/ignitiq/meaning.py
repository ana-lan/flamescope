"""Meaning guard: catches answers that misread CFI-G's flow_terminated outcome.

flow_terminated = the flame was STILL BURNING when the fuel flow was stopped.
A known model mistake is to say the flame went out or was extinguished because
the flow stopped. The number checks cannot see this, so this guard flags it and
the agent's repair round rewrites the sentence.

Self-test (no LLM calls):  uv run python -m ignitiq.meaning
"""
from __future__ import annotations

import re
import sys

# Only check answers that talk about CFI-G outcomes.
SCOPE_RE = re.compile(r"CFI-G|PSI-159|flow[_\s-]?terminat", re.I)

# "fuel flow was stopped", "flow terminated", "flow termination",
# "stopping the fuel flow", "flow stop"
FLOW_STOP_RE = re.compile(
    r"\b(?:fuel\s+)?flow\s+(?:was\s+|were\s+|is\s+|being\s+)?"
    r"(?:stopped|terminated|shut\s+off|cut\s+off|turned\s+off|ended|halted)\b"
    r"|\bflow[_\s-]?terminat\w*"
    r"|\b(?:stopp?ing|terminating|shutting\s+off|cutting\s+off|ending)\s+"
    r"(?:the\s+)?(?:fuel\s+)?flow\b"
    r"|\bflow\s+stop\w*",
    re.I,
)

# The flame went out.
EXTINGUISH_RE = re.compile(
    r"\b(?:extinguish\w*|went\s+out|go(?:es)?\s+out|going\s+out|put\s+out|"
    r"quench\w*|snuff\w*|died\s+out|blown\s+out|blew\s+out)\b",
    re.I,
)

# Clauses with these words describe the outcome correctly.
EXEMPT_RE = re.compile(
    r"self[-_\s]?extinguish|on\s+(?:its|their)\s+own|"
    r"still\s+(?:burning|flowing|lit)|kept\s+burning|"
    r"continued\s+(?:to\s+)?burn|remained\s+(?:lit|burning)|"
    r"\bbefore\b|"
    r"\b(?:not|never|no|none|neither|nor|didn't|did\s+not|without)\b",
    re.I,
)

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
CLAUSE_SPLIT_RE = re.compile(r"[;,:]|\s+(?:but|whereas|although|though)\s+", re.I)

REPAIR_HINT = (
    "In CFI-G, the outcome flow_terminated means the flame was STILL BURNING "
    "when the fuel flow was stopped. Stopping the flow is how the test ended; "
    "it does not mean the flame went out or was extinguished. Only "
    "self_extinguished means the flame went out on its own. Rewrite each "
    "flagged sentence so it says the flame was still burning when the fuel "
    "flow was stopped. Keep every number and citation unchanged."
)


def meaning_issues(answer: str) -> list[dict]:
    """Return one issue per clause that ties stopping the fuel flow to the
    flame going out. Empty list = no misread found."""
    if not answer or not SCOPE_RE.search(answer):
        return []
    issues: list[dict] = []
    for sentence in SENTENCE_SPLIT_RE.split(answer):
        sentence = sentence.strip()
        if not sentence or not FLOW_STOP_RE.search(sentence):
            continue
        for clause in CLAUSE_SPLIT_RE.split(sentence):
            if EXTINGUISH_RE.search(clause) and not EXEMPT_RE.search(clause):
                issues.append({
                    "kind": "flow_terminated_misread",
                    "sentence": sentence,
                    "clause": clause.strip(),
                })
                break  # one issue per sentence is enough
    return issues


# ---------------------------------------------------------------- self-test

_BAD = [
    "In the lunar box, 5 CFI-G flames were extinguished when the fuel flow was stopped [PSI-159].",
    "5 CFI-G tests ended by flow termination, meaning the flame was put out [PSI-159].",
    "Stopping the fuel flow extinguished 5 of the CFI-G flames [PSI-159].",
    "5 flames went out after the fuel flow was stopped (flow_terminated) [PSI-159].",
]

_GOOD = [
    # the in-box sentence the tool gives the model
    "11 CFI-G tests in the box: 5 still burning when the fuel flow was stopped; "
    "4 went out on its own while fuel was still flowing; 2 with no recorded outcome.",
    # the cached CFI-G answer
    "About one-third of the CFI-G flames (33.7%) kept burning until the fuel flow "
    "was stopped when the ambient O2 fraction was 30% or more [PSI-159]. By contrast, "
    "none of the tests with O2 below 25% showed that behavior [PSI-159].",
    "4 CFI-G flames went out before the fuel flow was stopped, and 5 were still "
    "burning when it was stopped [PSI-159].",
    "None of the CFI-G flames went out when the fuel flow was stopped [PSI-159].",
    "4 CFI-G flames self-extinguished and 5 were burning at flow termination [PSI-159].",
    # out of scope: FLEX, not CFI-G
    "FLEX droplets were extinguished more often with CO2 after the flow stopped [PSI-69].",
]


def _self_test() -> int:
    failures = 0
    for text in _BAD:
        ok = bool(meaning_issues(text))
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  flagged      {text[:70]}")
    for text in _GOOD:
        ok = not meaning_issues(text)
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  not flagged  {text[:70]}")
    total = len(_BAD) + len(_GOOD)
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_self_test())