import unittest

from app.services.filtering import BooleanExpressionError, filter_items_by_expression, parse_boolean_expression


ITEMS = [
    {
        "id": 1,
        "title": "Knowledge graph for digital libraries",
        "authors": "Alice",
        "journal": "Journal of Information Behavior",
        "summary": "This article studies LLM assisted catalog work.",
        "doi": "10.1000/kg1",
    },
    {
        "id": 2,
        "title": "Survey of library systems",
        "authors": "Bob",
        "journal": "Review Quarterly",
        "summary": "A broad survey paper.",
        "doi": "10.1000/survey2",
    },
    {
        "id": 3,
        "title": "Information behavior with archives",
        "authors": "Carol",
        "journal": "Archives Today",
        "summary": "Focuses on information behavior and archival search.",
        "doi": "",
    },
]


class BooleanFilteringTest(unittest.TestCase):
    def test_parser_accepts_nested_boolean_expression(self):
        tree = parse_boolean_expression('("knowledge graph" OR LLM) AND NOT survey')
        self.assertIsNotNone(tree)

    def test_filter_items_supports_field_queries(self):
        matched = filter_items_by_expression(
            ITEMS,
            'title:LLM OR summary:"information behavior" AND NOT journal:Review',
        )
        self.assertEqual([item["id"] for item in matched], [3])

    def test_filter_items_supports_grouped_field_scope(self):
        matched = filter_items_by_expression(ITEMS, 'journal:(archives OR behavior)')
        self.assertEqual([item["id"] for item in matched], [1, 3])

    def test_invalid_expression_raises(self):
        with self.assertRaises(BooleanExpressionError):
            filter_items_by_expression(ITEMS, "LLM AND OR survey")


if __name__ == "__main__":
    unittest.main()
