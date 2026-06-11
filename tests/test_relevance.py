import unittest

from app.relevance import RelevanceItem, build_relevance_prompt, item_from_record, parse_relevance_response


class RelevanceContractTest(unittest.TestCase):
    def test_prompt_requires_boolean_only_output(self):
        prompt = build_relevance_prompt(
            RelevanceItem(
                title="OpenAI releases a new RSS summarization model",
                summary="The release improves feed filtering and article ranking.",
            ),
            user_interest="AI tools for reading RSS feeds",
        )

        self.assertIn("Return exactly one lowercase token", prompt)
        self.assertIn("- true: relevant", prompt)
        self.assertIn("- false: not relevant", prompt)
        self.assertIn("Do not return JSON.", prompt)
        self.assertIn("Do not include reasons", prompt)

    def test_parse_relevance_response_accepts_only_boolean_tokens(self):
        cases = [("true", True), ("false", False), (" TRUE \n", True), ("\nfalse ", False)]
        for response_text, expected in cases:
            with self.subTest(response_text=response_text):
                self.assertIs(parse_relevance_response(response_text), expected)

    def test_parse_relevance_response_rejects_reasons_and_non_contract_output(self):
        invalid_outputs = [
            "{\"relevant\": true, \"reason\": \"matches the topic\"}",
            "true because it discusses RSS",
            "相关",
            "不相关",
            "",
        ]
        for response_text in invalid_outputs:
            with self.subTest(response_text=response_text):
                with self.assertRaisesRegex(ValueError, "Expected exactly"):
                    parse_relevance_response(response_text)

    def test_item_from_record_uses_existing_reader_fields(self):
        item = item_from_record(
            {
                "title": "A paper title",
                "summary": "An abstract",
                "link": "https://example.com/paper",
                "authors": "Alice; Bob",
                "journal": "Example Journal",
            }
        )

        self.assertEqual(item.title, "A paper title")
        self.assertEqual(item.summary, "An abstract")
        self.assertEqual(item.url, "https://example.com/paper")
        self.assertEqual(item.authors, "Alice; Bob")
        self.assertEqual(item.journal, "Example Journal")


if __name__ == "__main__":
    unittest.main()
