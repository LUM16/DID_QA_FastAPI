"""Tests for Neo4j client connection reuse."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import neo4j_client


class _FakeDriver:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class Neo4jClientTests(unittest.TestCase):
    def tearDown(self) -> None:
        neo4j_client.close_driver()

    def test_get_driver_reuses_matching_configuration(self) -> None:
        first = _FakeDriver()
        with (
            patch("neo4j_client.load_env"),
            patch("neo4j_client.GraphDatabase.driver", return_value=first) as mock_driver_factory,
            patch.dict(
                os.environ,
                {
                    "NEO4J_URI": "bolt://example:7687",
                    "NEO4J_USERNAME": "neo4j",
                    "NEO4J_PASSWORD": "secret",
                },
                clear=False,
            ),
        ):
            first_result = neo4j_client.get_driver()
            second_result = neo4j_client.get_driver()

            mock_driver_factory.assert_called_once_with(
                "bolt://example:7687", auth=("neo4j", "secret")
            )
        self.assertIs(first_result, first)
        self.assertIs(second_result, first)
        self.assertEqual(first.close_calls, 0)

    def test_get_driver_recreates_when_configuration_changes(self) -> None:
        first = _FakeDriver()
        second = _FakeDriver()

        with (
            patch("neo4j_client.load_env"),
            patch("neo4j_client.GraphDatabase.driver", side_effect=[first, second]),
        ):
            with patch.dict(
                os.environ,
                {
                    "NEO4J_URI": "bolt://example:7687",
                    "NEO4J_USERNAME": "neo4j",
                    "NEO4J_PASSWORD": "secret",
                },
                clear=False,
            ):
                self.assertIs(neo4j_client.get_driver(), first)

            with patch.dict(
                os.environ,
                {
                    "NEO4J_URI": "bolt://other:7687",
                    "NEO4J_USERNAME": "neo4j",
                    "NEO4J_PASSWORD": "secret",
                },
                clear=False,
            ):
                self.assertIs(neo4j_client.get_driver(), second)

        self.assertEqual(first.close_calls, 1)
        self.assertEqual(second.close_calls, 0)


if __name__ == "__main__":
    unittest.main()
