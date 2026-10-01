import io
import json
import unittest
from unittest.mock import patch

from tools.news_standardize import call_doubao


class NewsStandardizeTests(unittest.TestCase):
    def test_article_json_braces_reach_the_model_unchanged(self):
        article = '接口返回 {"items":[{"id":1}]}。'
        reply = '{"summary":"接口更新","category":"科技"}'
        response = io.BytesIO(json.dumps({
            "choices": [{"message": {"content": reply}}]
        }).encode("utf-8"))

        with patch("urllib.request.urlopen", return_value=response) as open_url:
            self.assertEqual(call_doubao(article, "test-key"), reply)

        request = open_url.call_args.args[0]
        prompt = json.loads(request.data)["messages"][0]["content"]
        self.assertIn(article, prompt)
        self.assertNotIn('{{"items"', prompt)


if __name__ == "__main__":
    unittest.main()
