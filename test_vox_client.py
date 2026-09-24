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
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class VoxClientTests(unittest.TestCase):
    def tearDown(self) -> None:
        vox_client.clear_llm_client_cache()

    def test_empty_limited_completion_retries_without_max_tokens(self) -> None:
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
        with (
            patch("vox_client.build_llm_client", return_value=(client, "model-a")),
            patch("vox_client._langfuse_generation", return_value=nullcontext(None)),
        ):
            text, usage = vox_client.chat("system", "user", max_tokens=400)

        self.assertIn("MATCH (n)", text)
        self.assertEqual(client.completions.calls[0]["max_tokens"], 400)
        self.assertNotIn("max_tokens", client.completions.calls[1])
        self.assertEqual(usage["prompt_tokens"], 20)
        self.assertEqual(usage["completion_tokens"], 5)
        self.assertEqual(usage["total_tokens"], 25)

    def test_build_llm_client_reuses_matching_configuration(self) -> None:
        client = _FakeClient([])
        with (
            patch("vox_client.load_env"),
            patch("vox_client._vox_configured", return_value=True),
            patch("vox_client._env", return_value="gpt-4o"),
            patch("vox_client._require_http_url", return_value="https://vox.example"),
            patch("vox_client.get_vox_access_token", return_value="token-a"),
            patch("vox_client.OpenAI", return_value=client) as mock_openai,
        ):
            first, first_model = vox_client.build_llm_client()
            second, second_model = vox_client.build_llm_client()

            mock_openai.assert_called_once_with(
                api_key="token-a", base_url="https://vox.example/v1"
            )
            self.assertIs(first, client)
            self.assertIs(second, client)
            self.assertEqual(first_model, "gpt-4o")
            self.assertEqual(second_model, "gpt-4o")

    def test_build_llm_client_recreates_after_token_change(self) -> None:
        first_client = _FakeClient([])
        second_client = _FakeClient([])
        with (
            patch("vox_client.load_env"),
            patch("vox_client._vox_configured", return_value=True),
            patch("vox_client._env", return_value="gpt-4o"),
            patch("vox_client._require_http_url", return_value="https://vox.example"),
            patch("vox_client.get_vox_access_token", side_effect=["token-a", "token-b"]),
            patch("vox_client.OpenAI", side_effect=[first_client, second_client]) as mock_openai,
        ):
            self.assertIs(vox_client.build_llm_client()[0], first_client)
            self.assertIs(vox_client.build_llm_client()[0], second_client)

            self.assertEqual(mock_openai.call_count, 2)


if __name__ == "__main__":
    unittest.main()
