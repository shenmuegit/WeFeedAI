import unittest

from tools.news_deduplicate import parse_dedup_response


class ParseDedupResponseTests(unittest.TestCase):
    def test_overlapping_groups_keep_one_earliest_article(self):
        self.assertEqual(parse_dedup_response("2,3\n1,2", 5), {1, 4, 5})

    def test_disjoint_groups_keep_unmentioned_articles(self):
        self.assertEqual(parse_dedup_response("2,4\n3,5", 6), {1, 2, 3, 6})

    def test_no_duplicates_keeps_all_articles(self):
        self.assertEqual(parse_dedup_response("无重复", 3), {1, 2, 3})


if __name__ == "__main__":
    unittest.main()
