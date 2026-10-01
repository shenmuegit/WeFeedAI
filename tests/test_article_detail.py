import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from src.crawler.article_detail import ArticleDetailCrawler


class ArticleDetailCrawlerTests(unittest.TestCase):
    def test_batch_fetches_each_url_once(self):
        crawler = object.__new__(ArticleDetailCrawler)
        crawler.logger = Mock()
        crawler.thread_pool_size = 2
        crawler.crawl_article = AsyncMock(side_effect=lambda url: f"content: {url}")

        results = asyncio.run(crawler.crawl_articles_batch(["a", "b", "a"]))

        self.assertEqual(results, {"a": "content: a", "b": "content: b"})
        self.assertEqual(crawler.crawl_article.await_count, 2)


if __name__ == "__main__":
    unittest.main()
