"""Tests for effort-prediction routing in the Q&A agent."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import agent


PREDICTION = {
    "person": "Chen, Zhenchao (Riven)",
    "did": "C5001001_59",
    "study": "C5001001",
    "prediction_type": "total_hours",
    "as_of_date": "2026-09-11",
    "p50_hours": 14.0,
    "p80_hours": 40.0,
    "p90_hours": 80.0,
    "model_version": "did-effort-ridge-v1",
    "person_completed_did_count": 123,
    "similarity_features": {
        "similar_did_count_ge_85": 3,
        "overall_prior_coverage": 1.0,
        "tlf_unseen_count": 0,
        "adam_unseen_count": 0,
        "sdtm_unseen_count": 0,
    },
    "similar_historical_dids": [
        {
            "did": "C5001001_19",
            "study": "C5001001",
            "completion_date": "2026-08-01",
            "actual_hours": 14.4,
            "overall_similarity": 1.0,
            "tlf_semantic_similarity": 1.0,
            "adam_similarity": 1.0,
            "sdtm_similarity": 1.0,
        }
    ],
    "warnings": [],
}


class AgentPredictionTests(unittest.TestCase):
    def _parameter_response(
        self, person: str, did: str, as_of_date: str | None = None
    ) -> tuple[str, dict[str, int]]:
        return (
            json.dumps(
                {"person": person, "did": did, "as_of_date": as_of_date}
            ),
            {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        )

    @patch("agent.person_name_candidates", return_value=["Chen, Zhenchao (Riven)"])
    @patch("agent._chat")
    def test_prediction_context_fills_missing_person_or_did(
        self, mock_chat, mock_candidates
    ) -> None:
        history = [{"role": "assistant", "content": "Prior prediction", "prediction": PREDICTION}]
        mock_chat.side_effect = [
            self._parameter_response("Chen, Zhenchao (Riven)", "C5001001_60"),
            self._parameter_response("Chen, Zhenchao (Riven)", "C5001001_59"),
            self._parameter_response("Chen, Zhenchao (Riven)", "C5001001_59"),
        ]

        did_only, did_only_usage = agent.extract_effort_prediction_parameters(
            "预测 C5001001_60", history
        )
        person_only, person_only_usage = agent.extract_effort_prediction_parameters(
            "预测 Riven", history
        )
        reference, reference_usage = agent.extract_effort_prediction_parameters(
            "这个 DID 需要多久？", history
        )

        self.assertEqual(did_only["person"], "Chen, Zhenchao (Riven)")
        self.assertEqual(did_only["did"], "C5001001_60")
        self.assertEqual(person_only["person"], "Chen, Zhenchao (Riven)")
        self.assertEqual(person_only["did"], "C5001001_59")
        self.assertEqual(reference["person"], "Chen, Zhenchao (Riven)")
        self.assertEqual(reference["did"], "C5001001_59")
        self.assertEqual(did_only_usage["total_tokens"], 6)
        self.assertEqual(person_only_usage["total_tokens"], 6)
        self.assertEqual(reference_usage["total_tokens"], 6)

    def test_did_next_to_chinese_text_uses_new_did_and_context_person(self) -> None:
        history = [{"role": "assistant", "content": "Prior prediction", "prediction": PREDICTION}]

        with (
            patch("agent.person_name_candidates", return_value=["Chen, Zhenchao (Riven)"]),
            patch(
                "agent._chat",
                return_value=self._parameter_response(
                    "Chen, Zhenchao (Riven)", "C1071007_142"
                ),
            ),
        ):
            parameters, usage = agent.extract_effort_prediction_parameters(
                "我问的是C1071007_142她要花多少时间", history
            )

        self.assertEqual(parameters["person"], "Chen, Zhenchao (Riven)")
        self.assertEqual(parameters["did"], "C1071007_142")
        self.assertEqual(usage["total_tokens"], 6)

    def test_did_next_to_chinese_text_keeps_explicit_person(self) -> None:
        with (
            patch("agent.person_name_candidates", return_value=["Lu, Manman"]),
            patch(
                "agent._chat",
                return_value=self._parameter_response("Lu, Manman", "C1071007_142"),
            ),
        ):
            parameters, usage = agent.extract_effort_prediction_parameters(
                "LUMANMAN C1071007_142要花多少时间"
            )

        self.assertEqual(parameters["person"], "Lu, Manman")
        self.assertEqual(parameters["did"], "C1071007_142")
        self.assertEqual(usage["total_tokens"], 6)

    @patch("agent.predict_effort", return_value=PREDICTION)
    @patch("agent.person_name_candidates", return_value=["Chen, Zhenchao (Riven)"])
    @patch("agent._chat")
    def test_contextual_did_replacement_routes_with_llm_parameters(
        self, mock_chat, mock_candidates, mock_predict
    ) -> None:
        history = [{"role": "assistant", "content": "Prior prediction", "prediction": PREDICTION}]
        mock_chat.side_effect = [
            self._parameter_response(
                "Chen, Zhenchao (Riven)", "C5001001_60", "2026-09-11"
            ),
        ]

        result = agent.ask("换成 C5001001_60", history=history)

        mock_predict.assert_called_once_with(
            person="Chen, Zhenchao (Riven)",
            did="C5001001_60",
            as_of_date="2026-09-11",
        )
        self.assertEqual(result["usage"]["total_tokens"], 6)

    @patch("agent.predict_effort", return_value=PREDICTION)
    @patch("agent.person_name_candidates", return_value=["Chen, Zhenchao (Riven)"])
    @patch(
        "agent._chat",
    )
    def test_llm_classifies_flexible_forecast_wording(
        self, mock_chat, mock_candidates, mock_predict
    ) -> None:
        history = [{"role": "assistant", "content": "Prior prediction", "prediction": PREDICTION}]
        mock_chat.side_effect = [
            (
                '{"intent":"effort_prediction"}',
                {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            ),
            self._parameter_response(
                "Chen, Zhenchao (Riven)", "C5001001_60", "2026-09-11"
            ),
        ]

        result = agent.ask("C5001001_60 大概要投入多久？", history=history)

        self.assertEqual(mock_chat.call_count, 2)
        mock_predict.assert_called_once_with(
            person="Chen, Zhenchao (Riven)",
            did="C5001001_60",
            as_of_date="2026-09-11",
        )
        self.assertEqual(result["usage"]["total_tokens"], 12)

    def test_prediction_intent_does_not_match_historical_hours(self) -> None:
        self.assertTrue(
            agent._is_effort_prediction_question(
                "预测 Riven 完成 C5001001_59 需要多少工时？"
            )
        )
        self.assertTrue(
            agent._is_effort_prediction_question(
                "Predict Riven's effort for C5001001_59"
            )
        )
        self.assertFalse(
            agent._is_effort_prediction_question(
                "Riven在C5001001_59已经花了多少小时？"
            )
        )

    @patch("agent.predict_effort", return_value=PREDICTION)
    @patch("agent.person_name_candidates", return_value=["Chen, Zhenchao (Riven)"])
    @patch("agent._chat")
    def test_ask_routes_prediction_without_schema_or_cypher(
        self, mock_chat, mock_candidates, mock_predict
    ) -> None:
        mock_chat.return_value = self._parameter_response("Riven", "C5001001_59")
        result = agent.ask("预测 Riven 完成 C5001001_59 需要多少工时？")

        self.assertEqual(mock_chat.call_count, 1)
        mock_predict.assert_called_once_with(
            person="Riven", did="C5001001_59", as_of_date=None
        )
        self.assertEqual(result["cypher"], "")
        self.assertEqual(result["prediction"]["p50_hours"], 14.0)
        self.assertIn("建议排期（P80）：**40.0 小时**", result["answer"])
        self.assertIn("预测可信度：**高**", result["answer"])
        self.assertIn("人员匹配：输入 `Riven`", result["answer"])
        self.assertIn("TLF 标题近似度 100%", result["answer"])
        self.assertIn("ADaM 相似度 100%", result["answer"])
        self.assertIn("SDTM 相似度 100%", result["answer"])
        self.assertNotIn("总体相似度", result["answer"])
        self.assertEqual(result["usage"]["total_tokens"], 6)
        self.assertEqual(
            set(result["timings_ms"]),
            {"intent", "prediction_parameters", "prediction_model", "answer_generation"},
        )
        self.assertTrue(all(value >= 0 for value in result["timings_ms"].values()))

    @patch("agent.person_name_candidates", return_value=["Chen, Zhenchao (Riven)"])
    @patch("agent._chat")
    def test_llm_parameter_extraction_supports_english(
        self, mock_chat, mock_candidates
    ) -> None:
        mock_chat.return_value = self._parameter_response("Riven", "C5001001_59")
        parameters, usage = agent.extract_effort_prediction_parameters(
            "Predict Riven's effort for C5001001_59"
        )

        self.assertEqual(parameters["person"], "Riven")
        self.assertEqual(parameters["did"], "C5001001_59")
        self.assertEqual(usage["total_tokens"], 6)

    @patch(
        "agent._chat",
        return_value=(
            '{"person":"Lumanman","did":"C1071007_141","as_of_date":null}',
            {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        ),
    )
    @patch("agent.person_name_candidates", return_value=["Lu, Manman"])
    def test_did_before_person_uses_llm_parameter_extraction(
        self, mock_candidates, mock_chat
    ) -> None:
        parameters, usage = agent.extract_effort_prediction_parameters(
            "predict C1071007_141 hours for Lumamman"
        )

        mock_chat.assert_called_once()
        mock_candidates.assert_called_once()
        self.assertEqual(parameters["person"], "Lumanman")
        self.assertEqual(parameters["did"], "C1071007_141")
        self.assertEqual(usage["total_tokens"], 6)

    @patch(
        "agent._chat",
        return_value=(
            '{"person":"Lu, Manman","did":"C1071007_141","as_of_date":null}',
            {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        ),
    )
    @patch("agent.person_name_candidates", return_value=["Lu, Manman"])
    def test_llm_removes_english_person_phrase_before_matching(
        self, mock_candidates, mock_chat
    ) -> None:
        parameters, usage = agent.extract_effort_prediction_parameters(
            "estimate how many working hours for LUMANMAN IN C1071007_141"
        )

        mock_candidates.assert_called_once()
        mock_chat.assert_called_once()
        self.assertEqual(parameters["person"], "Lu, Manman")
        self.assertEqual(parameters["did"], "C1071007_141")
        self.assertEqual(usage["total_tokens"], 6)


if __name__ == "__main__":
    unittest.main()
