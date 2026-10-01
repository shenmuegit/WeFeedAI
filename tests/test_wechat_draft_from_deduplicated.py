import io
import json
import unittest
from unittest.mock import patch

from tools.wechat_draft_from_deduplicated import _call_doubao_wechat_format


class WechatDraftFormatTests(unittest.TestCase):
    def test_json_braces_reach_formatting_model_unchanged(self):
        plain_text = '科技\n\n1. 接口返回 {"items":[{"id":1}]}。'
        response = io.BytesIO(json.dumps({
            "choices": [{"message": {"content": "<p>摘要</p>"}}]
        }).encode("utf-8"))

        with patch("urllib.request.urlopen", return_value=response) as open_url:
            self.assertEqual(
                _call_doubao_wechat_format(plain_text, "test-key"),
                "<p>摘要</p>",
            )

        request = open_url.call_args.args[0]
        prompt = json.loads(request.data)["messages"][0]["content"]
        self.assertIn(plain_text, prompt)
        self.assertNotIn('{{"items"', prompt)


if __name__ == "__main__":
    unittest.main()
