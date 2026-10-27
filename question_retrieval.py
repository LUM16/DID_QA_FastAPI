"""Offline-reviewed, question-level retrieval without category filtering."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer

from example_memory import tokenize

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent
EXAMPLES_ROOT = ROOT / "docs" / "examples"
REVIEW_PATH = ROOT / "docs" / "question_bank_review.json"
TOP_K = 3
EXAMPLE_MAX_CHARS = 2200
EXCLUDED_FILES = frozenset({"sensitive_excluded.md"})
QUESTION_HEADING = re.compile(
    r"^## ((?:(?:dashboard_)?q|sub)\d+(?:_\d+)?):[ \t]*(.+)$", re.MULTILINE,
)

EXAMPLE_KEYWORDS = {
    "person_productivity.md": (
        "person", "productivity", "hands-on", "hour", "hours", "task", "tasks",
        "complete", "completed", "workload", "ntid", "员工", "工时", "任务",
    ),
    "workload_planning.md": (
        "capacity", "plan", "planned", "ongoing", "workload", "resource", "规划", "负载",
    ),
    "study_delivery.md": ("study", "delivery", "did", "status", "里程碑", "交付"),
    "submission.md": (
        "submission", "dsp", "project_name", "submission lead", "dataset",
        "datasets", "递交", "数据集",
    ),
    "lot_tlf_sdtm_adam.md": ("lot", "tlf", "sdtm", "adam", "submission", "产出物"),
    "team_manager.md": (
        "manager", "group lead", "ta lead", "team", "reports to", "org", "org chart",
        "organization", "hierarchy", "经理", "团队", "组织",
    ),
    "reporting_dashboard.md": (
        "dashboard", "kpi", "trend", "monthly", "reporting", "看板", "报表",
    ),
}
DEFAULT_EXAMPLES = (
    "query_index.md", "study_delivery.md", "workload_planning.md",
    "person_productivity.md", "lot_tlf_sdtm_adam.md", "team_manager.md",
    "reporting_dashboard.md", "uncategorized.md",
)


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    text: str
    source: str
    source_sha256: str
    retrieval_text: str
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class Match:
    question: Question
    score: float


def select_example_files(question: str, limit: int = 1) -> list[str]:
    """Preserve the original keyword/file selection for the comparison baseline."""
    if limit < 1:
        raise ValueError("Example file limit must be positive.")
    scored = [
        (sum(keyword in question.lower() for keyword in keywords), filename)
        for filename, keywords in EXAMPLE_KEYWORDS.items()
    ]
    scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [filename for _, filename in scored[:limit]]
    for filename in DEFAULT_EXAMPLES:
        if len(selected) >= limit:
            break
        if filename not in selected:
            selected.append(filename)
    return selected


def source_paths(root: Path = EXAMPLES_ROOT) -> tuple[Path, ...]:
    paths = tuple(
        path for path in sorted(root.glob("*.md"))
        if path.name not in EXCLUDED_FILES
    )
    if not paths:
        raise ValueError(f"No safe question-bank sources found in {root}.")
    return paths


def load_questions(root: Path = EXAMPLES_ROOT) -> tuple[Question, ...]:
    questions: list[Question] = []
    seen: set[str] = set()
    for path in source_paths(root):
        content = path.read_text(encoding="utf-8")
        headings = list(QUESTION_HEADING.finditer(content))
        for index, heading in enumerate(headings):
            identifier, title = heading.groups()
            if identifier in seen:
                raise ValueError(f"Duplicate question ID: {identifier}")
            seen.add(identifier)
            end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
            text = content[heading.start():end].strip()
            if not re.search(r"```cypher\s*\n.+?```", text, re.DOTALL | re.IGNORECASE):
                raise ValueError(f"{identifier} has no complete Cypher example.")
            questions.append(Question(
                id=identifier, question=title.strip(), text=text, source=path.name,
                source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                retrieval_text=title.strip(),
            ))
    if len(questions) < TOP_K:
        raise ValueError("The safe bank must contain at least three questions.")
    return tuple(sorted(questions, key=lambda item: item.id))


def apply_reviews(
    questions: tuple[Question, ...], review_path: Path = REVIEW_PATH,
) -> tuple[Question, ...]:
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("reviews"), list):
        raise ValueError("Unsupported question-bank review format.")
    reviews: dict[str, dict] = {}
    for review in payload["reviews"]:
        if not isinstance(review, dict) or not isinstance(review.get("id"), str):
            raise ValueError("Each review must contain a question ID.")
        identifier = review["id"]
        if identifier in reviews:
            raise ValueError(f"Duplicate review ID: {identifier}")
        reviews[identifier] = review
    expected = {question.id for question in questions}
    if set(reviews) != expected:
        raise ValueError(
            f"Review coverage mismatch: missing={sorted(expected - set(reviews))}, "
            f"unknown={sorted(set(reviews) - expected)}"
        )
    reviewed = []
    for question in questions:
        review = reviews[question.id]
        if (
            review.get("question") != question.question
            or review.get("source_sha256") != question.source_sha256
        ):
            raise ValueError(f"Stale review for {question.id}; review the changed source again.")
        text, issues = review.get("retrieval_text"), review.get("issues")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Missing reviewed retrieval text for {question.id}.")
        if not isinstance(issues, list) or any(not isinstance(issue, str) for issue in issues):
            raise ValueError(f"Invalid review issues for {question.id}.")
        reviewed.append(replace(question, retrieval_text=text.strip(), issues=tuple(issues)))
    return tuple(reviewed)


class QuestionIndex:
    def __init__(self, questions: tuple[Question, ...]) -> None:
        if len(questions) < TOP_K:
            raise ValueError("An index requires at least three questions.")
        self.questions = questions
        self.vectorizer = TfidfVectorizer(
            tokenizer=tokenize, token_pattern=None, lowercase=False,
            ngram_range=(1, 2), sublinear_tf=True,
        )
        self.matrix = self.vectorizer.fit_transform(
            question.retrieval_text for question in questions
        )

    def search(
        self, question: str, *, candidates: set[str] | None = None,
        warn_on_no_overlap: bool = True,
    ) -> list[Match]:
        if not question.strip():
            raise ValueError("Retrieval question must not be blank.")
        vector = self.vectorizer.transform([question])
        positions = [
            index for index, item in enumerate(self.questions)
            if candidates is None or item.id in candidates
        ]
        if not positions:
            return []
        matrix = self.matrix if candidates is None else self.matrix[positions]
        scores = (matrix @ vector.T).toarray().ravel()
        ranked = sorted(
            range(len(positions)),
            key=lambda index: (-float(scores[index]), self.questions[positions[index]].id),
        )
        if warn_on_no_overlap and scores[ranked[0]] == 0:
            log.warning("Question retrieval has no lexical overlap; Top 3 scores are zero.")
        return [
            Match(self.questions[positions[index]], float(scores[index]))
            for index in ranked[:TOP_K]
        ]


@lru_cache(maxsize=1)
def _cached_index(fingerprint: tuple[tuple[str, int, int], ...]) -> QuestionIndex:
    return QuestionIndex(apply_reviews(load_questions()))


def get_index() -> QuestionIndex:
    paths = (*source_paths(), REVIEW_PATH)
    fingerprint = tuple(
        (str(path), stat.st_mtime_ns, stat.st_size)
        for path in paths for stat in [path.stat()]
    )
    return _cached_index(fingerprint)


def format_matches(matches: list[Match]) -> str:
    parts = ["Question-level references (up to 3; cosine scores are lexical, not confidence):"]
    for match in matches:
        item = match.question
        parts.append(f"Reference {item.id}; cosine={match.score:.6f}")
        if item.issues:
            parts.append(
                "Offline review cautions (validate against the live schema; "
                "do not copy questionable patterns): " + " | ".join(item.issues)
            )
        parts.append(item.text)
    return "\n\n".join(parts)


def retrieve_context(question: str) -> str:
    return format_matches(get_index().search(question))


def legacy_context(question: str, root: Path = EXAMPLES_ROOT) -> str:
    filename = select_example_files(question)[0]
    return (root / filename).read_text(encoding="utf-8")[:EXAMPLE_MAX_CHARS]
