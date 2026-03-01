"""内容处理协调器"""
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from .deepseek_client import DeepSeekClient
from ..utils.logger import get_logger


class ContentProcessor:
    """内容处理类"""
    
    def __init__(self, deepseek_client: DeepSeekClient, config: Dict[str, Any], logger=None):
        """
        初始化内容处理器
        
        Args:
            deepseek_client: DeepSeek 客户端
            config: AI 配置
            logger: 日志记录器
        """
        self.deepseek_client = deepseek_client
        self.config = config
        self.logger = logger or get_logger()
        self.thread_pool_size = config.get("thread_pool_size", 3)
        self.max_retries = config.get("max_retries", 3)
    
    def integrate_and_refine_article(self, article: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """整合多来源并精炼单篇文章"""
        sources = article.get("sources", [])
        if not sources:
            self.logger.warning(f"文章 {article.get('title')} 没有来源，跳过")
            return None
        
        # 准备来源内容
        sources_content = []
        for source in sources:
            sources_content.append({
                "source_name": source.get("source_name", ""),
                "content": source.get("content", ""),
                "url": source.get("url", "")
            })
        
        # 调用 AI 整合精炼
        refined_content = self.deepseek_client.integrate_and_refine(sources_content)
        
        if not refined_content:
            self.logger.error(f"文章 {article.get('title')} 精炼失败")
            return None
        
        # 构建精炼后的文章信息
        refined_article = {
            "title": article.get("title"),
            "url": article.get("url"),
            "topic": article.get("topic"),
            "publish_time": article.get("publish_time"),
            "refined_content": refined_content,
            "sources_count": len(sources),
            "original_sources": [
                {
                    "source_name": s.get("source_name"),
                    "url": s.get("url")
                }
                for s in sources
            ]
        }
        
        return refined_article
    
    def refine_articles_batch(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量精炼文章（线程池）"""
        self.logger.info(f"开始批量精炼 {len(articles)} 篇文章")
        
        refined_articles = []
        
        with ThreadPoolExecutor(max_workers=self.thread_pool_size) as executor:
            futures = {
                executor.submit(self.integrate_and_refine_article, article): article
                for article in articles
            }
            
            for future in as_completed(futures):
                article = futures[future]
                try:
                    refined = future.result()
                    if refined:
                        refined_articles.append(refined)
                except Exception as e:
                    self.logger.error(f"精炼文章失败 {article.get('title')}: {e}")
        
        self.logger.info(f"批量精炼完成，成功 {len(refined_articles)}/{len(articles)} 篇")
        return refined_articles
    
    def analyze_all_relationships(self, refined_articles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """分析所有文章的相关性"""
        self.logger.info("开始分析文章相关性")
        
        result = self.deepseek_client.analyze_relationships(refined_articles)
        
        if result:
            self.logger.info("相关性分析完成")
        else:
            self.logger.error("相关性分析失败")
        
        return result
    
    def generate_topic_articles(self, grouped_articles: Dict[str, List[Dict[str, Any]]]) -> Dict[str, str]:
        """按主题生成微信文章"""
        self.logger.info(f"开始生成 {len(grouped_articles)} 个主题的微信文章")
        
        topic_articles = {}
        
        for topic, articles in grouped_articles.items():
            if not articles:
                self.logger.warning(f"主题 {topic} 没有文章，跳过")
                continue
            
            # 收集所有精炼内容
            news_contents = [article.get("refined_content", "") for article in articles if article.get("refined_content")]
            
            if not news_contents:
                self.logger.warning(f"主题 {topic} 没有有效内容，跳过")
                continue
            
            # 生成微信文章
            wechat_article = self.deepseek_client.generate_wechat_article(topic, news_contents)
            
            if wechat_article:
                topic_articles[topic] = wechat_article
                self.logger.info(f"主题 {topic} 文章生成成功")
            else:
                self.logger.error(f"主题 {topic} 文章生成失败")
        
        self.logger.info(f"微信文章生成完成，成功 {len(topic_articles)}/{len(grouped_articles)} 篇")
        return topic_articles
    
    def process_articles(self, articles: List[Dict[str, Any]]) -> tuple:
        """
        处理所有文章
        
        Returns:
            (refined_articles, relationships, topic_articles)
        """
        # 1. 批量精炼
        refined_articles = self.refine_articles_batch(articles)
        
        # 2. 相关性分析
        relationships = self.analyze_all_relationships(refined_articles)
        
        # 3. 按主题分组
        grouped_articles = {}
        for article in refined_articles:
            topic = article.get("topic", "Unknown")
            if topic not in grouped_articles:
                grouped_articles[topic] = []
            grouped_articles[topic].append(article)
        
        # 4. 生成主题文章
        topic_articles = self.generate_topic_articles(grouped_articles)
        
        return refined_articles, relationships, topic_articles

