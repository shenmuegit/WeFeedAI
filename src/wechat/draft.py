"""微信草稿创建模块"""
import time
import requests
import html
import re
from typing import Dict, Any, List, Optional
from .auth import WeChatAuth
from ..utils.logger import get_logger


class WeChatDraft:
    """微信草稿类"""
    
    def __init__(self, auth: WeChatAuth, config: Dict[str, Any], logger=None):
        """
        初始化草稿类
        
        Args:
            auth: 微信认证对象
            config: 微信配置
            logger: 日志记录器
        """
        self.auth = auth
        self.config = config
        self.logger = logger or get_logger()
        self.api_base_url = config.get("api_base_url", "https://api.weixin.qq.com")
    
    def _convert_to_wechat_format(self, article_content: str, title: str, original_url: str = "") -> Dict[str, Any]:
        """转换文章内容为微信 API 格式"""
        # 清理 HTML，提取文本
        # 这里简化处理，假设 article_content 已经是 HTML 格式
        
        # 提取摘要（前200字）
        text_content = html.unescape(article_content)
        # 移除 HTML 标签获取纯文本
        text_only = re.sub(r'<[^>]+>', '', text_content)
        digest = text_only[:200] if len(text_only) > 200 else text_only
        
        article = {
            "article_type": "news",
            "title": title,
            "author": "",  # 可以配置默认作者
            "digest": digest,
            "content": article_content,
            "content_source_url": original_url,
            "need_open_comment": 0,
            "only_fans_can_comment": 0
        }
        
        return article
    
    def create_draft(self, article_content: str, title: str, original_url: str = "") -> Optional[str]:
        """创建单个草稿"""
        access_token = self.auth.get_access_token()
        if not access_token:
            self.logger.error("无法获取 access_token")
            return None
        
        url = f"{self.api_base_url}/cgi-bin/draft/add"
        params = {"access_token": access_token}
        
        # 转换为微信格式
        article = self._convert_to_wechat_format(article_content, title, original_url)
        
        data = {
            "articles": [article]
        }
        
        try:
            response = requests.post(url, params=params, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if "media_id" in result:
                self.logger.info(f"草稿创建成功: {title}")
                return result["media_id"]
            else:
                error_code = result.get("errcode", "unknown")
                error_msg = result.get("errmsg", "unknown")
                self.logger.error(f"创建草稿失败: {error_code} - {error_msg}")
                return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"创建草稿请求失败: {e}")
            return None
    
    def create_drafts_batch(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量创建草稿"""
        self.logger.info(f"开始批量创建 {len(articles)} 个草稿")
        
        results = []
        for article in articles:
            content = article.get("content", "")
            title = article.get("title", "")
            url = article.get("url", "")
            
            media_id = self.create_draft(content, title, url)
            results.append({
                "title": title,
                "media_id": media_id,
                "success": media_id is not None
            })
            
            # 延迟，避免请求过快
            time.sleep(1)
        
        success_count = sum(1 for r in results if r["success"])
        self.logger.info(f"批量创建完成，成功 {success_count}/{len(articles)} 个")
        
        return results

