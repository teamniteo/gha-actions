import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "collect", Path(__file__).with_name("collect.py")
)
assert spec is not None and spec.loader is not None
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)


class UsageTests(unittest.TestCase):
    def source(self, text):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "execution.json"
        path.write_text(text)
        return path

    def test_codex_cached_input_is_not_counted_twice(self):
        path = self.source(
            "\n".join(
                json.dumps(event)
                for event in [
                    {
                        "type": "item.completed",
                        "item": {"text": "private review content"},
                    },
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 80,
                            "output_tokens": 10,
                        },
                    },
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 50,
                            "cached_input_tokens": 20,
                            "output_tokens": 5,
                        },
                    },
                ]
            )
        )
        usage = collect.codex_usage(path, "gpt-6-sol")
        self.assertEqual(
            usage,
            [
                {
                    "model": "gpt-6-sol",
                    "tokens": {
                        "input": 50,
                        "cache_read": 100,
                        "cache_write": 0,
                        "output": 15,
                    },
                }
            ],
        )
        self.assertNotIn("private", json.dumps(usage))

    def test_claude_uses_model_totals_not_assistant_messages(self):
        path = self.source(
            json.dumps(
                [
                    {"type": "assistant", "message": {"usage": {"input_tokens": 999}}},
                    {
                        "type": "result",
                        "usage": {"input_tokens": 999},
                        "modelUsage": {
                            "claude-opus": {
                                "inputTokens": 10,
                                "outputTokens": 20,
                                "cacheReadInputTokens": 30,
                                "cacheCreationInputTokens": 40,
                            },
                            "claude-haiku": {
                                "inputTokens": 5,
                                "outputTokens": 6,
                                "cacheReadInputTokens": 0,
                                "cacheCreationInputTokens": 0,
                            },
                        },
                    },
                ]
            )
        )
        usage = collect.claude_usage(path)
        self.assertEqual(sum(sum(x["tokens"].values()) for x in usage), 111)
        self.assertEqual({x["model"] for x in usage}, {"claude-opus", "claude-haiku"})

    def test_missing_terminal_usage_is_unknown_not_zero(self):
        self.assertEqual(
            collect.codex_usage(self.source('{"type":"turn.failed"}'), "sol"), []
        )
        self.assertEqual(collect.claude_usage(self.source("[]")), [])

    def test_claude_error_result_still_counts_consumed_tokens(self):
        path = self.source(
            json.dumps(
                [
                    {
                        "type": "result",
                        "is_error": True,
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 20,
                            "cache_read_input_tokens": 30,
                            "cache_creation_input_tokens": 40,
                        },
                    }
                ]
            )
        )
        self.assertEqual(sum(collect.claude_usage(path)[0]["tokens"].values()), 100)

    def test_invalid_counts_rejected(self):
        for value in [-1, True, 0.5, "10"]:
            with self.assertRaises(ValueError):
                collect.count(value)


if __name__ == "__main__":
    unittest.main()
