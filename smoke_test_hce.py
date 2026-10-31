"""Manual end-to-end smoke test for the HCE branch (real LLM + real Neo4j).

Usage:
    export GITHUB_TOKEN=ghp_xxx          # or put it in .env
    .venv/bin/python smoke_test_hce.py ["自定义问题" ...]

Not a unit test: it calls GitHub Copilot and Neo4j, so it costs tokens.
"""

from __future__ import annotations

import os
import sys

from agent import ask
from neo4j_client import close_driver, load_env
from vox_client import use_llm_provider

DEFAULT_QUESTIONS = [
    "2026年1月到6月 China 组在 Oncology 上的 HCE 是多少？",
    "Chen, Sizhen 2026年上半年在 C1071032 上的 HCE",
    "Chen, Sizhen 的 HCE 是多少",          # no period -> should ask back
    "今年上半年中国组的人力投入",            # no 'HCE' keyword -> LLM routing
]


def main() -> None:
    load_env()
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        sys.exit("GITHUB_TOKEN is not set (env var or .env).")
    questions = sys.argv[1:] or DEFAULT_QUESTIONS
    try:
        with use_llm_provider("github_copilot", token):
            for q in questions:
                result = ask(q)
                print("=" * 80)
                print("Q:", q)
                print("timings:", result.get("timings_ms"))
                print("error:", result.get("error"))
                print(result.get("answer"))
    finally:
        close_driver()


if __name__ == "__main__":
    main()
