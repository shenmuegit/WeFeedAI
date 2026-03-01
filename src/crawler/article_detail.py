"""文章详细内容爬取模块"""
import asyncio
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.async_api import async_playwright, Page
from bs4 import BeautifulSoup
from ..utils.logger import get_logger
from ..utils.browser_config import get_browser_context_options, get_anti_detection_script, get_browser_launch_args


class ArticleDetailCrawler:
    """文章详细内容爬取类"""
    
    def __init__(self, config: Dict[str, Any], logger=None):
        """
        初始化爬取器
        
        Args:
            config: 爬取配置
            logger: 日志记录器
        """
        self.config = config
        self.logger = logger or get_logger()
        self.thread_pool_size = config.get("thread_pool_size", 5)
        self.max_retries = 3
        self.retry_delay = 2
        self.request_delay = config.get("request_delay", 1)
        self.session_file = config.get("session_file", "data/session_state.json")
        self.proxy = config.get("proxy", None)
    
    async def extract_article_content(self, page: Page, url: str) -> Optional[str]:
        """提取文章内容"""
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(self.request_delay)
            
            # 获取页面 HTML
            html = await page.content()
            
            # 使用 BeautifulSoup 解析
            soup = BeautifulSoup(html, 'html.parser')
            
            # 移除脚本和样式
            for script in soup(["script", "style", "nav", "header", "footer", "aside"]):
                script.decompose()
            
            # 尝试找到文章主体
            # 常见的文章容器标签
            article_selectors = [
                'article',
                '[role="article"]',
                '.article-content',
                '.post-content',
                '.entry-content',
                'main',
                '.content'
            ]
            
            content = None
            for selector in article_selectors:
                elements = soup.select(selector)
                if elements:
                    content = elements[0]
                    break
            
            if not content:
                # 如果没有找到特定容器，使用 body
                content = soup.find('body')
            
            if content:
                # 提取文本
                text = content.get_text(separator='\n', strip=True)
                # 清理多余空白
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                return '\n'.join(lines)
            
            return None
        except Exception as e:
            self.logger.error(f"提取文章内容失败 {url}: {e}")
            return None
    
    async def crawl_article(self, url: str) -> Optional[str]:
        """爬取单篇文章详细内容"""
        for attempt in range(self.max_retries):
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=True,
                        args=get_browser_launch_args()
                    )
                    
                    # 加载 session 和代理配置
                    storage_state = self.session_file if Path(self.session_file).exists() else None
                    context_options = get_browser_context_options(
                        storage_state=storage_state,
                        proxy=self.proxy
                    )
                    
                    context = await browser.new_context(**context_options)
                    
                    # 移除 webdriver 特征
                    await context.add_init_script(get_anti_detection_script())
                    page = await context.new_page()
                    
                    try:
                        content = await self.extract_article_content(page, url)
                        return content
                    finally:
                        await browser.close()
            except Exception as e:
                if attempt < self.max_retries - 1:
                    self.logger.warning(f"爬取文章失败，重试 {attempt + 1}/{self.max_retries}: {url}")
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    self.logger.error(f"爬取文章失败，已达最大重试次数: {url}, 错误: {e}")
                    return None
        
        return None
    
    async def crawl_articles_batch(self, urls: List[str]) -> Dict[str, Optional[str]]:
        """批量爬取文章（使用线程池）"""
        self.logger.info(f"开始批量爬取 {len(urls)} 篇文章")
        
        results = {}
        
        # 使用 asyncio 的并发控制
        semaphore = asyncio.Semaphore(self.thread_pool_size)
        
        async def crawl_with_semaphore(url):
            async with semaphore:
                content = await self.crawl_article(url)
                return url, content
        
        tasks = [crawl_with_semaphore(url) for url in urls]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in completed:
            if isinstance(result, Exception):
                self.logger.error(f"爬取任务异常: {result}")
            else:
                url, content = result
                results[url] = content
        
        success_count = sum(1 for v in results.values() if v is not None)
        self.logger.info(f"批量爬取完成，成功 {success_count}/{len(urls)} 篇")
        
        return results

