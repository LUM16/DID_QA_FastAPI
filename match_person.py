"""Resolve person mentions in a user prompt against Neo4j Person nodes.

Pipeline
--------
1. Ask the LLM to extract every person mention from the user prompt.
2. If nothing is extracted, return the prompt unchanged.
3. Load Person.Name / Person.NTID from Neo4j.
4. Match each mention against the roster:
   - exactly one match  -> rewrite that span of the prompt to the official Name
   - several matches    -> surface "Name [NTID]" choices for the Streamlit UI

The matching strategy is pluggable; see MATCH_STRATEGIES at the bottom.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any, Callable

from rapidfuzz.distance import Levenshtein
from starlette.requests import Request

from neo4j_client import load_env, run_cypher
from vox_client import add_usage, chat, empty_usage

PERSON_ROSTER_QUERY = """
MATCH (p:Person)
WHERE p.Name IS NOT NULL
  AND trim(p.Name) <> ''
  AND NOT toLower(trim(p.Name)) ENDS WITH '(contractor)'
RETURN DISTINCT p.Name AS name, p.NTID AS ntid
ORDER BY name
"""

# Names such as "Li Hua (Contractor)" are excluded from the roster, so a
# contractor is never a match candidate. The regex tolerates extra spaces and
# a trailing period/whitespace after the marker.
CONTRACTOR_SUFFIX = re.compile(r"\(\s*contractor\s*\)\s*\.?\s*$", re.IGNORECASE)


def is_contractor(name: str) -> bool:
    """True when the Person.Name ends with a "(Contractor)" marker."""
    return bool(CONTRACTOR_SUFFIX.search(str(name or "")))

EXTRACTION_SYSTEM = (
    "You extract person mentions from a question about clinical study staffing.\n"
    'Return JSON only, with exactly this shape: {"names": ["<mention>", ...]}\n'
    "Rules:\n"
    "1. Copy each mention verbatim from the question, preserving its original "
    "spelling, casing and spacing.\n"
    "2. Include nicknames, misspellings and partial names; do not correct them.\n"
    "3. Never invent a name that is absent from the question.\n"
    "4. Exclude study identifiers, DIDs, team names, therapeutic areas, "
    "deliverable names and job titles.\n"
    "5. Return an empty list when the question mentions no person.\n"
    "6. Output no markdown, commentary or explanation.\n"
    "Examples:\n"
    '- "predict C1071007_141 hours for Lumamman" -> {"names":["Lumamman"]}\n'
    '- "compare zhang wei and Li Hua workload" -> {"names":["zhang wei","Li Hua"]}\n'
    '- "how many TLFs are in study C1071007?" -> {"names":[]}'
)

JSON_OBJECT = re.compile(r"\{[\s\S]*\}")


# --------------------------------------------------------------------------- #
# Roster access
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def load_person_roster() -> tuple[dict[str, str], ...]:
    """Return every non-contractor Person node as {"name": ..., "ntid": ...}.

    Cached per process. Rows whose Name ends with "(Contractor)" are dropped,
    both in Cypher and again in Python (to catch trailing spaces/punctuation),
    so they never become match candidates.
    """
    load_env()
    return tuple(
        {"name": str(row["name"]).strip(), "ntid": str(row.get("ntid") or "").strip()}
        for row in run_cypher(PERSON_ROSTER_QUERY, limit_rows=100_000)
        if row.get("name") and not is_contractor(row["name"])
    )


def clear_roster_cache() -> None:
    """Drop the cached roster, e.g. after Person nodes change."""
    load_person_roster.cache_clear()


# --------------------------------------------------------------------------- #
# Step 1 - LLM extraction
# --------------------------------------------------------------------------- #
def _json_object(text: str) -> dict[str, Any]:
    match = JSON_OBJECT.search(text or "")
    if not match:
        raise ValueError(f"The LLM did not return a JSON object: {text!r}")
    return json.loads(match.group(0))


def extract_person_mentions(
    prompt: str,
    chat_fn: Callable[..., tuple[str, dict[str, int]]] = chat,
) -> tuple[list[str], dict[str, int]]:
    """Ask the LLM for every person mention in the prompt, verbatim."""
    raw, usage = chat_fn(EXTRACTION_SYSTEM, prompt, temperature=0)
    names = _json_object(raw).get("names")
    if not isinstance(names, list):
        raise ValueError('The LLM response is missing a "names" list.')

    mentions: list[str] = []
    for item in names:
        mention = str(item or "").strip()
        # Guard against hallucination: the mention must occur in the prompt.
        if mention and mention.lower() in prompt.lower() and mention not in mentions:
            mentions.append(mention)
    return mentions, usage


# --------------------------------------------------------------------------- #
# Step 4 - matching strategies
# --------------------------------------------------------------------------- #
def _normalize(value: Any) -> str:
    """Upper-case and strip everything that is not a letter or digit."""
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def match_exact(mention: str, roster: tuple[dict[str, str], ...]) -> list[dict[str, str]]:
    """Strategy A - normalized equality.

    "li hua" and "Li-Hua" both match "Li Hua". Strictest and cheapest; a
    misspelling such as "Lumamman" for "Lumanman" yields no match at all.
    """
    key = _normalize(mention)
    return [person for person in roster if _normalize(person["name"]) == key]


def match_substring(
    mention: str, roster: tuple[dict[str, str], ...]
) -> list[dict[str, str]]:
    """Strategy B - normalized containment, either direction.

    "Li" matches "Li Hua"; "Li Hua Wang" also matches "Li Hua". Handles partial
    names well, but common short surnames will return many candidates, which is
    exactly what the disambiguation list is for.
    """
    key = _normalize(mention)
    if not key:
        return []
    return [
        person
        for person in roster
        if key in _normalize(person["name"]) or _normalize(person["name"]) in key
    ]


def match_token(mention: str, roster: tuple[dict[str, str], ...]) -> list[dict[str, str]]:
    """Strategy C - token overlap, order independent.

    "Hua Li" matches "Li Hua", and "Wei" matches "Zhang Wei". A person matches
    when every token of the mention appears among that person's name tokens.
    """
    tokens = {_normalize(part) for part in re.split(r"\s+", mention) if _normalize(part)}
    if not tokens:
        return []
    matched = []
    for person in roster:
        name_tokens = {
            _normalize(part) for part in re.split(r"\s+", person["name"]) if _normalize(part)
        }
        if tokens <= name_tokens:
            matched.append(person)
    return matched


# A mention contained in a name (or in one of its tokens) is a deliberate
# partial name far more often than a coincidence, so it floors at a high score
# instead of being penalised for the characters it omits.
CONTAINMENT_SCORE = 0.85


def _edit_ratio(left: str, right: str) -> float:
    """Levenshtein similarity in [0, 1]; 1.0 means identical.

    Backed by rapidfuzz's C++ implementation. rapidfuzz scores two empty
    strings as 1.0; we keep the 0.0 convention so an empty mention can never
    float to the top of the candidate list.
    """
    if not left or not right:
        return 0.0
    return Levenshtein.normalized_similarity(left, right)


def _name_tokens(name: str) -> list[str]:
    """Normalized name parts, split on whitespace and commas."""
    return [_normalize(part) for part in re.split(r"[\s,]+", str(name)) if _normalize(part)]


def _similarity(key: str, name: str) -> float:
    """Score a normalized mention against one roster name.

    Uses Levenshtein (via rapidfuzz) rather than SequenceMatcher because a
    single substituted letter splits SequenceMatcher's contiguous blocks and
    roughly halves the score: "MAMMAN" vs "MANMAN" rates 0.50 there but 0.83
    here, which is why that typo used to rank below unrelated names such as
    "Ma, Mengran".

    The mention is scored against the whole name *and* each token, so a given
    name can match on its own instead of being dragged down by an unrelated
    surname ("MAMMAN" vs "MANMAN" rather than vs "LUMANMAN").
    """
    whole = _normalize(name)
    best = _edit_ratio(key, whole)
    if key and key in whole:
        best = max(best, CONTAINMENT_SCORE)
    for token in _name_tokens(name):
        best = max(best, _edit_ratio(key, token))
        if key and key in token:
            best = max(best, CONTAINMENT_SCORE)
    return best


def match_fuzzy(
    mention: str,
    roster: tuple[dict[str, str], ...],
    threshold: float = 0.45,
    margin: float = 0.25,
    n_max: int = 12,
) -> list[dict[str, str]]:
    """Strategy D - token-aware edit-distance similarity with a tie margin.

    Tolerates typos ("mamman" -> "Lu, Manman"). Scores every roster entry, keeps
    those at or above `threshold`, then returns only the entries within `margin`
    of the best score, sorted by descending similarity and truncated to the top
    `n_max` candidates, so the best matches are always the ones surfaced.
    """
    key = _normalize(mention)
    if not key:
        return []

    scored = [(_similarity(key, person["name"]), person) for person in roster]
    viable = [(score, person) for score, person in scored if score >= threshold]
    if not viable:
        return []

    best = max(score for score, _ in viable)
    near_best = [(score, person) for score, person in viable if best - score <= margin]
    # Descending score, then name, so equally-scored candidates stay stable.
    near_best.sort(key=lambda item: (-item[0], _normalize(item[1]["name"])))
    if n_max is not None and n_max > 0:
        near_best = near_best[:n_max]

    return [person for _, person in near_best]

def match_ntid(mention: str, roster: tuple[dict[str, str], ...]) -> list[dict[str, str]]:
    """Strategy F - normalized equality against Person.NTID.

    Lets the user type an NTID ("chens291") instead of a display name.
    """
    key = _normalize(mention)
    if not key:
        return []
    return [person for person in roster if person.get("ntid") and _normalize(person["ntid"]) == key]


def match_layered(mention: str, roster: tuple[dict[str, str], ...]) -> list[dict[str, str]]:
    """Strategy E - NTID, exact, then token, then fuzzy; first non-empty layer wins.

    Recommended default: precise when the user types a full official name, still
    forgiving for partial names and typos, and it avoids the noise of running
    fuzzy matching on inputs that already matched exactly.
    """
    for strategy in (match_ntid, match_exact, match_token, match_fuzzy):
        matched = strategy(mention, roster)
        if matched:
            return matched
    return []


MATCH_STRATEGIES: dict[str, Callable[[str, tuple[dict[str, str], ...]], list[dict[str, str]]]] = {
    "exact": match_exact,
    "substring": match_substring,
    "token": match_token,
    "fuzzy": match_fuzzy,
    "ntid": match_ntid,
    "layered": match_layered,
}


# --------------------------------------------------------------------------- #
# Prompt rewriting
# --------------------------------------------------------------------------- #
def _replace_mention(prompt: str, mention: str, official: str) -> str:
    """Replace the mention case-insensitively, on word boundaries where possible."""
    return _replace_mentions(prompt, {mention: official})


def _replace_mentions(prompt: str, mapping: dict[str, str]) -> str:
    """Replace every mention in one pass, so substituted names are never re-matched.

    Rewriting mentions one at a time corrupts the prompt when an official name
    contains another mention: "sizhen and chen" would first become
    "Chen, Sizhen and chen", and the later "chen" rule would then also hit the
    "Chen" that was just inserted. A single alternation pass avoids that because
    `re.sub` never rescans the text it has already emitted.
    """
    pending = {
        mention: official
        for mention, official in (mapping or {}).items()
        if mention and mention != official
    }
    if not pending:
        return prompt

    # Longest mentions first so "Chen, Sizhen" wins over the bare "Chen".
    ordered = sorted(pending, key=len, reverse=True)
    parts = []
    for mention in ordered:
        bounded = rf"(?<!\w){re.escape(mention)}(?!\w)"
        # Fall back to a loose match only when the mention never appears as a
        # standalone word (e.g. it is glued to punctuation the LLM dropped).
        usable = bounded if re.search(bounded, prompt, re.IGNORECASE) else re.escape(mention)
        parts.append(f"(?P<m{len(parts)}>{usable})")

    pattern = re.compile("|".join(parts), re.IGNORECASE)

    def _substitute(match: re.Match[str]) -> str:
        index = int(match.lastgroup[1:])  # type: ignore[union-attr]
        return pending[ordered[index]]

    return pattern.sub(_substitute, prompt)


def format_choice(person: dict[str, str]) -> str:
    """Render a candidate as "Name [NTID]" for the Streamlit picker."""
    ntid = person.get("ntid")
    return f"{person['name']} [{ntid}]" if ntid else person["name"]


# --------------------------------------------------------------------------- #
# Self reference ("I" / "我") handling
# --------------------------------------------------------------------------- #
# Mentions of the speaker are resolved from the environment (get_current_ntid)
# instead of the LLM roster extraction: the prompt carries no name to match.
# Longer alternatives come first so "myself" is not consumed by "my".
SELF_REFERENCE = re.compile(
    r"(?<!\w)(?:i'm|i've|myself|mine|my|me|i)(?!\w)"
    r"|我们|咱们|我方|本人|我",
    re.IGNORECASE,
)

# Suffixes appended to the official name so the rewritten prompt stays
# grammatical: possessives become "<Name>'s", contractions expand to a verb.
_SELF_SUFFIX = {
    "i'm": " is",
    "i've": " has",
    "my": "'s",
    "mine": "'s",
}


def find_self_references(prompt: str) -> list[str]:
    """Return the verbatim self-reference tokens found in `prompt`."""
    return SELF_REFERENCE.findall(prompt or "")


def find_person_by_ntid(
    ntid: str, roster: tuple[dict[str, str], ...] | None = None
) -> dict[str, str] | None:
    """Look up a roster entry by NTID; None when the NTID is unknown."""
    key = _normalize(ntid)
    if not key:
        return None
    roster = load_person_roster() if roster is None else roster
    matched = match_ntid(key, roster)
    return dict(matched[0]) if matched else None


def resolve_self_references(
    prompt: str,
    ntid_fn: Callable[..., str] | None = None,
    roster: tuple[dict[str, str], ...] | None = None,
    request: Request | None = None,
) -> tuple[str, list[dict[str, str]], list[str]]:
    """Replace "I"/"我"-style mentions with the current user's official name.

    Returns
    -------
    (rewritten_prompt, resolved, unresolved)
      resolved   : [{"mention": "I", "name": ..., "ntid": ...}, ...] - one entry
                   per distinct self-reference token that was substituted.
      unresolved : the self-reference tokens left untouched because the current
                   NTID is unavailable or absent from the roster.
    """
    tokens = find_self_references(prompt)
    if not tokens:
        return prompt, [], []

    # Default resolver reads the Posit Connect headers off the FastAPI request;
    # a caller-supplied `ntid_fn` is treated as a zero-argument callable.
    if ntid_fn is None:
        ntid = (get_current_ntid(request) or "").strip()
    else:
        ntid = (ntid_fn() or "").strip()
    person = find_person_by_ntid(ntid, roster) if ntid else None
    if person is None:
        # Fall back to the bare NTID when it is not in the roster, so downstream
        # matching can still key off it; give up entirely when there is no NTID.
        if not ntid:
            return prompt, [], sorted({token.lower() for token in tokens})
        person = {"name": ntid, "ntid": ntid}

    def _substitute(match: re.Match[str]) -> str:
        return person["name"] + _SELF_SUFFIX.get(match.group(0).lower(), "")

    rewritten = SELF_REFERENCE.sub(_substitute, prompt)
    resolved = [
        {"mention": token, "name": person["name"], "ntid": person.get("ntid", "")}
        for token in sorted({token for token in tokens})
    ]
    return rewritten, resolved, []


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def match_person_in_prompt(
    prompt: str,
    strategy: str = "layered",
    chat_fn: Callable[..., tuple[str, dict[str, int]]] = chat,
    ntid_fn: Callable[..., str] | None = None,
    request: Request | None = None,
) -> dict[str, Any]:
    """Resolve person mentions in `prompt` against Neo4j Person nodes.

    Self references ("I", "me", "my", "我", "本人", ...) are rewritten to the
    current user's official name, resolved from `ntid_fn` (defaults to
    `get_current_ntid`) and looked up by NTID in the roster.

    Returns
    -------
    dict with keys:
      prompt       : the rewritten prompt (unchanged when nothing resolved)
      status       : "no_person" | "resolved" | "needs_choice" | "unknown"
      mentions     : the verbatim mentions the LLM extracted
      resolved     : [{"mention":..., "name":..., "ntid":...}, ...]
      ambiguous    : [{"mention":..., "choices":["Name [NTID]", ...],
                       "candidates":[{"name":...,"ntid":...}, ...]}, ...]
      unmatched    : mentions with no roster match
      usage        : LLM token usage
    """
    if strategy not in MATCH_STRATEGIES:
        raise ValueError(
            f"Unknown strategy {strategy!r}; choose one of {sorted(MATCH_STRATEGIES)}."
        )
    match_fn = MATCH_STRATEGIES[strategy]

    usage = empty_usage()

    # Step 0 - resolve "I"/"我" against the logged-in user before the LLM sees
    # the prompt, so the extractor only deals with real names.
    prompt, self_resolved, self_unresolved = resolve_self_references(
        prompt, ntid_fn=ntid_fn, request=request
    )

    mentions, extraction_usage = extract_person_mentions(prompt, chat_fn)
    usage = add_usage(usage, extraction_usage)

    # Step 2 - no person mentioned, hand the prompt back untouched.
    if not mentions:
        return {
            "prompt": prompt,
            "status": "resolved" if self_resolved else ("unknown" if self_unresolved else "no_person"),
            "mentions": [],
            "resolved": self_resolved,
            "ambiguous": [],
            "unmatched": self_unresolved,
            "usage": usage,
        }

    # Step 3 - roster from Neo4j.
    roster = load_person_roster()

    resolved: list[dict[str, str]] = [dict(item) for item in self_resolved]
    unmatched: list[str] = list(self_unresolved)

    # Match every mention first, without touching the prompt. Rewriting as we
    # go is what caused "sizhen and chen" to cascade into nested names.
    candidates_by_mention: list[tuple[str, list[dict[str, str]]]] = []
    for mention in mentions:
        matched = match_fn(mention, roster)
        if matched:
            candidates_by_mention.append((mention, [dict(p) for p in matched]))
        else:
            unmatched.append(mention)

    # Only a genuinely ambiguous mention forces a round-trip. Several mentions
    # that each match exactly one person need no confirmation, because
    # `_replace_mentions` already substitutes them atomically.
    defer = any(len(cands) > 1 for _, cands in candidates_by_mention)

    ambiguous: list[dict[str, Any]] = []
    replacements: dict[str, str] = {}

    for mention, cands in candidates_by_mention:
        if len(cands) > 1:
            # Only these need a picker in the UI.
            ambiguous.append(
                {
                    "mention": mention,
                    "choices": [format_choice(person) for person in cands],
                    "candidates": cands,
                    "default": "",
                    "certain": False,
                }
            )
        elif defer:
            # Single match, but another mention is still open: hold it back so
            # the whole prompt is rewritten in one go, and surface it to the UI
            # as an already-settled entry (no prompt box, just context).
            ambiguous.append(
                {
                    "mention": mention,
                    "choices": [format_choice(cands[0])],
                    "candidates": cands,
                    "default": format_choice(cands[0]),
                    "certain": True,
                }
            )
        else:
            person = cands[0]
            replacements[mention] = person["name"]
            resolved.append(
                {"mention": mention, "name": person["name"], "ntid": person.get("ntid", "")}
            )

    # Apply all substitutions at once; see `_replace_mentions` for why.
    rewritten = _replace_mentions(prompt, replacements)

    if ambiguous:
        status = "needs_choice"
    elif resolved:
        status = "resolved"
    else:
        status = "unknown"

    return {
        "prompt": rewritten,
        "status": status,
        "mentions": mentions,
        "resolved": resolved,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "usage": usage,
    }


# Sentinel the UI can send back for a mention the user does not want rewritten:
# the mention is dropped from `ambiguous` and the prompt keeps its wording.
KEEP_ORIGINAL = "__keep_original__"


def apply_person_choice(prompt: str, mention: str, choice: str) -> str:
    """Rewrite `prompt` once the user picks a "Name [NTID]" entry in Streamlit."""
    official = choice.split(" [")[0].strip() if " [" in choice else choice.strip()
    return _replace_mention(prompt, mention, official)


def apply_person_choices(result: dict[str, Any], choices: dict[str, str]) -> dict[str, Any]:
    """Fold the user's disambiguation picks back into a match result.

    Parameters
    ----------
    result  : the dict returned by `match_person_in_prompt`.
    choices : {mention: "Name [NTID]"} as selected in the UI. Mentions that are
              absent (or mapped to a falsy value) stay ambiguous.

    Returns a new result dict with the same keys: chosen mentions move from
    `ambiguous` into `resolved`, `prompt` is rewritten to the official names,
    and `status` is recomputed. The input dict is not mutated.
    """
    prompt = result["prompt"]
    resolved = [dict(item) for item in result.get("resolved", [])]
    still_ambiguous: list[dict[str, Any]] = []
    replacements: dict[str, str] = {}
    kept: list[str] = list(result.get("kept_original", []))

    for item in result.get("ambiguous", []):
        mention = item["mention"]
        raw = (choices or {}).get(mention) or ""
        if raw == KEEP_ORIGINAL:
            # The user says none of the candidates is right: leave the mention
            # verbatim in the prompt instead of forcing a wrong substitution.
            kept.append(mention)
            continue
        # Fall back to the pre-selected certain match when the UI sends nothing
        # back for this mention; only genuinely open choices stay ambiguous.
        choice = raw or item.get("default") or ""
        if not choice:
            still_ambiguous.append(item)
            continue

        # Recover the NTID from the matching candidate rather than parsing it
        # back out of the label, so the stored record stays authoritative.
        official = choice.split(" [")[0].strip() if " [" in choice else choice.strip()
        candidate = next(
            (c for c in item.get("candidates", []) if c.get("name") == official),
            {"name": official, "ntid": ""},
        )
        replacements[mention] = candidate["name"]
        resolved.append(
            {"mention": mention, "name": candidate["name"], "ntid": candidate.get("ntid", "")}
        )

    prompt = _replace_mentions(prompt, replacements)

    if still_ambiguous:
        status = "needs_choice"
    elif resolved:
        status = "resolved"
    elif result.get("unmatched"):
        status = "unknown"
    else:
        status = result["status"]

    return {
        **result,
        "prompt": prompt,
        "status": status,
        "resolved": resolved,
        "ambiguous": still_ambiguous,
        "kept_original": kept,
    }


def get_current_ntid(request: Request | None = None) -> str:
    """NTID from the Posit Connect viewer, if this request is running as that user.

    Returns "" when no request is available (e.g. a script run outside FastAPI).
    """
    if request is None:
        return ""
    raw = (
        request.headers.get("rstudio-connect-credentials")
        or request.headers.get("posit-connect-credentials")
        or ""
    ).strip()
    username = ""
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict):
            username = str(data.get("user") or data.get("username") or "").strip()
    if not username:
        username = (
            request.headers.get("x-forwarded-user")
            or request.headers.get("remote-user")
            or ""
        ).strip()
    if not username:
        return ""
    if "\\" in username:
        username = username.rsplit("\\", 1)[-1]
    if "@" in username:
        username = username.split("@", 1)[0]
    return username.strip().upper()


# --------------------------------------------------------------------------- #
# Usage example
# --------------------------------------------------------------------------- #
# Run with:  python test_match_person.py "predict C1071007_141 hours for Lumamman"
#
# Requires NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD (and optionally
# NEO4J_DATABASE) in .env or the environment, because the roster is read live
# from Neo4j via PERSON_ROSTER_QUERY.
# if __name__ == "__main__":

#     # prompt = "list the delivery for Chen"
#     # prompt = "list the delivery for riven"
#     # prompt = "list the delivery for chens291"
#     # prompt = "list the delivery for zhenchao and chen"
#     # prompt = "list the delivery for Chen, Sizhen"
#     prompt = "list the delivery for mamman"
#     # prompt = "list all the did for SDSA"

#     # 1. Inspect the roster loaded from Neo4j (Name + NTID).
#     roster = load_person_roster()

#     # 2. Resolve the mentions in the prompt.
#     result = match_person_in_prompt(prompt, strategy="layered")

#     print(f"\nOriginal prompt : {prompt}")
#     print(f"Rewritten prompt: {result['prompt']}")
#     print(f"Status          : {result['status']}")
#     print(f"Mentions        : {result['mentions']}")
#     print(f"Resolved        : {result['resolved']}")
#     print(f"Unmatched       : {result['unmatched']}")

#     # 3. When several people match a mention, present the choices and apply one.
#     #    In Streamlit this is where you would render st.selectbox(...).
#     final_prompt = result["prompt"]
#     for item in result["ambiguous"]:
#         print(f"\nAmbiguous mention {item['mention']!r}, choices:")
#         for choice in item["choices"]:
#             print("   ", choice)
#         # Demo: take the first choice; replace with the user's UI selection.
#         final_prompt = apply_person_choice(final_prompt, item["mention"], item["choices"][0])

#     print(f"\nFinal prompt    : {final_prompt}")


    


