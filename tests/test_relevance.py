import unittest

from app.relevance import parse_llm_review_response


class RelevanceContractTest(unittest.TestCase):
    def test_parse_llm_review_response_is_strict(self):
        self.assertEqual(parse_llm_review_response("high"), "high")
        self.assertEqual(parse_llm_review_response(" LOW "), "low")
        with self.assertRaisesRegex(ValueError, "high.*low"):
            parse_llm_review_response("pending")


if __name__ == "__main__":
    unittest.main()
