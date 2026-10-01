import unittest
from unittest.mock import Mock, patch

from src.wechat.draft import WeChatDraft


class WeChatDraftTests(unittest.TestCase):
    def test_news_draft_sends_configured_cover_media_id(self):
        auth = Mock()
        auth.get_access_token.return_value = "access-token"
        response = Mock()
        response.json.return_value = {"media_id": "draft-id"}
        draft = WeChatDraft(auth, {
            "draft": {"default_thumb_media_id": "cover-id"},
        }, logger=Mock())

        with patch("src.wechat.draft.requests.post", return_value=response) as post:
            self.assertEqual(draft.create_draft("<p>News</p>", "Title"), "draft-id")

        article = post.call_args.kwargs["json"]["articles"][0]
        self.assertEqual(article["thumb_media_id"], "cover-id")

    def test_missing_cover_skips_invalid_news_draft_request(self):
        auth = Mock()
        draft = WeChatDraft(auth, {"draft": {}}, logger=Mock())

        with patch("src.wechat.draft.requests.post") as post:
            self.assertIsNone(draft.create_draft("<p>News</p>", "Title"))

        auth.get_access_token.assert_not_called()
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
