"""Tests for the Vox GenAI client wrapper."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import vox_client


def _response(text: str, prompt_tokens: int = 2, completion_tokens: int = 3):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=text)),
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.completions = _FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


class VoxClientTests(unittest.TestCase):
    @patch("vox_client._langfuse_generation")
    @patch("vox_client.build_llm_client")
    def test_empty_limited_completion_retries_without_max_tokens(
        self, mock_build_llm_client, mock_langfuse_generation
    ) -> None:
        client = _FakeClient(
            [
                _response("", prompt_tokens=10, completion_tokens=0),
                _response(
                    "```cypher\nMATCH (n) RETURN n LIMIT 1\n```",
                    prompt_tokens=10,
                    completion_tokens=5,
                ),
            ]
        )
        mock_build_llm_client.return_value = (client, "model-a")
        mock_langfuse_generation.return_value = nullcontext(None)

        text, usage = vox_client.chat("system", "user", max_tokens=400)

        self.assertIn("MATCH (n)", text)
        self.assertEqual(client.completions.calls[0]["max_tokens"], 400)
        self.assertNotIn("max_tokens", client.completions.calls[1])
        self.assertEqual(usage["prompt_tokens"], 20)
        self.assertEqual(usage["completion_tokens"], 5)
        self.assertEqual(usage["total_tokens"], 25)


if __name__ == "__main__":
    unittest.main()
