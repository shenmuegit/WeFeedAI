"""主程序入口"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from playwright.async_api import async_playwright
from .utils.browser_config import get_browser_context_options, get_anti_detection_script, get_browser_launch_args

from .utils.config_loader import (
    load_config,
    load_selectors,
    get_crawler_config,
    get_ai_config,
    get_wechat_config,
    get_scheduler_config,
    get_logging_config,
    get_topics_config
)
from .utils.logger import setup_logger
from .utils.deduplicator import Deduplicator
from .crawler.google_news import GoogleNewsCrawler
from .crawler.article_detail import ArticleDetailCrawler
from .ai.deepseek_client import DeepSeekClient
from .ai.content_processor import ContentProcessor
from .wechat.auth import WeChatAuth
from .wechat.draft import WeChatDraft
from .wechat.publish import WeChatPublish


class WeFeedAI:
    """WeFeedAI 主类"""
    
    def __init__(self):
        """初始化"""
        # 加载配置
        self.config = load_config()
        self.selectors = load_selectors()
        
        # 设置日志
        logging_config = get_logging_config(self.config)
        self.logger = setup_logger(
            log_file=logging_config.get("file", "logs/app.log"),
            level=logging_config.get("level", "INFO"),
            format_str=logging_config.get("format")
        )
        
        # 初始化模块
        crawler_config = get_crawler_config(self.config)
        ai_config = get_ai_config(self.config)
        wechat_config = get_wechat_config(self.config)
        
        # 去重器
        today = datetime.now().strftime("%Y-%m-%d")
        self.deduplicator = Deduplicator(date=today)
        
        # 爬取模块
        self.google_news_crawler = GoogleNewsCrawler(crawler_config, self.selectors, self.logger)
        self.article_detail_crawler = ArticleDetailCrawler(crawler_config, self.logger)
        
        # AI 模块
        self.deepseek_client = DeepSeekClient(ai_config, self.logger)
        self.content_processor = ContentProcessor(self.deepseek_client, ai_config, self.logger)
        
        # 微信模块
        self.wechat_auth = WeChatAuth(wechat_config, self.logger)
        self.wechat_draft = WeChatDraft(self.wechat_auth, wechat_config, self.logger)
        self.wechat_publish = WeChatPublish(self.wechat_auth, wechat_config, self.logger)
    
    async def crawl_google_news(self) -> List[Dict[str, Any]]:
        """爬取 Google News"""
        self.logger.info("=== 开始爬取 Google News ===")
        
        # 获取主题配置
        topics_config = get_topics_config(self.config)
        
        # 访问主页获取主题链接
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=get_browser_launch_args()
            )
            
            session_file = Path(self.google_news_crawler.session_file)
            crawler_config = get_crawler_config(self.config)
            proxy = crawler_config.get("proxy", None)
            
            storage_state = str(session_file) if session_file.exists() else None
            context_options = get_browser_context_options(
                storage_state=storage_state,
                proxy=proxy
            )
            
            context = await browser.new_context(**context_options)
            
            # 移除 webdriver 特征
            await context.add_init_script(get_anti_detection_script())
            page = await context.new_page()
            
            try:
                await page.goto(self.google_news_crawler.google_news_url, wait_until="networkidle")
                
                # 检查登录
                if not await self.google_news_crawler.check_login(page):
                    self.logger.error("未登录，请先运行 tools/login.py 登录")
                    raise Exception("未登录状态")
                
                # 获取主题链接
                topic_links = await self.google_news_crawler.get_topic_links(page)
                
                # 匹配配置中的主题
                matched_topics = []
                for topic_config in topics_config:
                    topic_name = topic_config.get("name", "")
                    # 在链接中查找匹配的主题
                    for link in topic_links:
                        if topic_name.lower() in link.get("name", "").lower():
                            matched_topics.append({
                                "name": topic_name,
                                "url": link.get("url", "")
                            })
                            break
                
                self.logger.info(f"找到 {len(matched_topics)} 个匹配的主题")
            finally:
                await browser.close()
        
        # 爬取所有主题
        all_articles = await self.google_news_crawler.crawl_all_topics(matched_topics)
        
        self.logger.info(f"Google News 爬取完成，共 {len(all_articles)} 条新闻")
        return all_articles
    
    async def crawl_article_details(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """爬取文章详细内容"""
        self.logger.info("=== 开始爬取文章详细内容 ===")
        
        # 收集所有来源 URL
        all_urls = []
        url_to_article = {}
        
        for article in articles:
            sources = article.get("sources", [])
            for source in sources:
                url = source.get("url", "")
                if url and not self.deduplicator.is_processed(url):
                    all_urls.append(url)
                    if url not in url_to_article:
                        url_to_article[url] = []
                    url_to_article[url].append((article, source))
        
        self.logger.info(f"需要爬取 {len(all_urls)} 个来源的详细内容")
        
        # 批量爬取
        contents = await self.article_detail_crawler.crawl_articles_batch(all_urls)
        
        # 将内容添加到文章
        for url, content in contents.items():
            if content:
                # 标记为已处理
                self.deduplicator.mark_processed(url)
                
                # 添加到对应的来源
                if url in url_to_article:
                    for article, source in url_to_article[url]:
                        source["content"] = content
        
        # 保存去重记录
        self.deduplicator.save()
        
        # 保存原始数据
        today = datetime.now().strftime("%Y-%m-%d")
        articles_file = Path(f"data/articles_{today}.json")
        articles_file.parent.mkdir(parents=True, exist_ok=True)
        with open(articles_file, 'w', encoding='utf-8') as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"文章详细内容爬取完成，已保存到 {articles_file}")
        return articles
    
    def process_with_ai(self, articles: List[Dict[str, Any]]) -> tuple:
        """AI 处理"""
        self.logger.info("=== 开始 AI 处理 ===")
        
        # 处理文章
        refined_articles, relationships, topic_articles = self.content_processor.process_articles(articles)
        
        # 保存精炼结果
        today = datetime.now().strftime("%Y-%m-%d")
        refined_file = Path(f"data/refined_{today}.json")
        with open(refined_file, 'w', encoding='utf-8') as f:
            json.dump(refined_articles, f, ensure_ascii=False, indent=2)
        
        # 保存相关性数据
        if relationships:
            relationships_file = Path(f"data/relationships/{today}.json")
            relationships_file.parent.mkdir(parents=True, exist_ok=True)
            with open(relationships_file, 'w', encoding='utf-8') as f:
                json.dump(relationships, f, ensure_ascii=False, indent=2)
        
        self.logger.info("AI 处理完成")
        return refined_articles, relationships, topic_articles
    
    def publish_to_wechat(self, topic_articles: Dict[str, str]):
        """发布到微信"""
        self.logger.info("=== 开始发布到微信 ===")
        
        # 准备文章列表
        articles = []
        for topic, content in topic_articles.items():
            articles.append({
                "title": f"{topic} - {datetime.now().strftime('%Y-%m-%d')}",
                "content": content,
                "url": ""
            })
        
        # 创建草稿
        draft_results = self.wechat_draft.create_drafts_batch(articles)
        
        # 提取成功的 media_id
        media_ids = [r["media_id"] for r in draft_results if r["success"]]
        
        # 发布草稿
        if media_ids:
            publish_results = self.wechat_publish.publish_drafts_batch(media_ids)
            self.logger.info(f"微信发布完成，成功 {sum(1 for r in publish_results if r['success'])}/{len(media_ids)} 篇")
        else:
            self.logger.warning("没有成功的草稿可以发布")
    
    async def run_daily_task(self):
        """执行每日任务"""
        try:
            self.logger.info("=" * 50)
            self.logger.info(f"开始执行每日任务 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 1. 爬取 Google News
            articles = await self.crawl_google_news()
            if not articles:
                self.logger.warning("未爬取到任何新闻，任务结束")
                return
            
            # 2. 爬取文章详细内容
            articles_with_content = await self.crawl_article_details(articles)
            
            # 3. AI 处理
            refined_articles, relationships, topic_articles = self.process_with_ai(articles_with_content)
            
            # 4. 发布到微信
            if topic_articles:
                self.publish_to_wechat(topic_articles)
            else:
                self.logger.warning("没有生成微信文章")
            
            self.logger.info("每日任务执行完成")
            self.logger.info("=" * 50)
        except Exception as e:
            self.logger.error(f"执行每日任务失败: {e}", exc_info=True)


def main():
    """主函数"""
    app = WeFeedAI()
    
    # 检查是否启用定时任务
    scheduler_config = get_scheduler_config(app.config)
    if scheduler_config.get("enabled", False):
        cron_expr = scheduler_config.get("cron", "0 9 * * *")
        app.logger.info(f"定时任务已启用，cron: {cron_expr}")
        
        scheduler = BlockingScheduler()
        
        # 解析 cron 表达式
        parts = cron_expr.split()
        if len(parts) == 5:
            minute, hour, day, month, weekday = parts
            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=weekday
            )
        else:
            # 默认每天 9 点
            trigger = CronTrigger(hour=9, minute=0)
        
        scheduler.add_job(
            lambda: asyncio.run(app.run_daily_task()),
            trigger=trigger,
            id='daily_task',
            name='每日新闻处理任务'
        )
        
        app.logger.info("定时任务已启动，等待执行...")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            app.logger.info("定时任务已停止")
    else:
        # 立即执行一次
        app.logger.info("定时任务未启用，立即执行一次")
        asyncio.run(app.run_daily_task())


if __name__ == "__main__":
    main()

