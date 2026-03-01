"""DeepSeek API 客户端"""
import time
from typing import List, Dict, Any, Optional
import requests
from ..utils.logger import get_logger


class DeepSeekClient:
    """DeepSeek API 客户端类"""
    
    def __init__(self, config: Dict[str, Any], logger=None):
        """
        初始化客户端
        
        Args:
            config: AI 配置
            logger: 日志记录器
        """
        self.config = config
        self.logger = logger or get_logger()
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url", "https://api.deepseek.com")
        self.model = config.get("model", "deepseek-chat")
        self.temperature = config.get("temperature", 0.7)
        self.max_tokens = config.get("max_tokens", 4000)
        self.max_retries = config.get("max_retries", 3)
        self.retry_delay = config.get("retry_delay", 2)
    
    def _make_request(self, messages: List[Dict[str, str]], **kwargs) -> Optional[Dict[str, Any]]:
        """发送 API 请求"""
        url = f"{self.base_url}/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens)
        }
        
        # 添加其他参数
        if "stream" in kwargs:
            data["stream"] = kwargs["stream"]
        
        for attempt in range(self.max_retries):
            try:
                response = requests.post(url, headers=headers, json=data, timeout=60)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    self.logger.warning(f"API 请求失败，重试 {attempt + 1}/{self.max_retries}: {e}")
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    self.logger.error(f"API 请求失败，已达最大重试次数: {e}")
                    return None
        
        return None
    
    def chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Optional[str]:
        """调用 Chat Completion API"""
        response = self._make_request(messages, **kwargs)
        if response and "choices" in response and len(response["choices"]) > 0:
            return response["choices"][0]["message"]["content"]
        return None
    
    def refine_content(self, content: str, original_url: str = "") -> Optional[str]:
        """精炼单篇内容"""
        prompt = f"""请精炼以下新闻内容，保留关键信息和核心观点，语言简洁明了：

{content}

要求：
1. 保留关键信息和核心观点
2. 语言简洁明了
3. 保留原文链接：{original_url}
"""
        
        messages = [
            {"role": "system", "content": "你是一个专业的新闻编辑，擅长精炼新闻内容。"},
            {"role": "user", "content": prompt}
        ]
        
        return self.chat_completion(messages)
    
    def integrate_and_refine(self, sources_content: List[Dict[str, str]]) -> Optional[str]:
        """整合多来源内容并精炼"""
        if not sources_content:
            return None
        
        sources_text = ""
        for i, source in enumerate(sources_content, 1):
            source_name = source.get("source_name", f"来源{i}")
            content = source.get("content", "")
            url = source.get("url", "")
            sources_text += f"\n\n来源 {i} ({source_name}):\n{content}\n原文链接: {url}"
        
        prompt = f"""请分析以下同一新闻的多个来源报道，整合为一篇精炼的综合报道：

{sources_text}

要求：
1. 整合所有来源的关键信息
2. 保留重要的观点差异（如有）
3. 生成客观、平衡的综合报道
4. 语言简洁明了，适合普通读者
5. 保留所有来源的原文链接
"""
        
        messages = [
            {"role": "system", "content": "你是一个专业的新闻编辑，擅长整合多来源新闻并生成综合报道。"},
            {"role": "user", "content": prompt}
        ]
        
        return self.chat_completion(messages)
    
    def analyze_relationships(self, refined_articles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """分析所有文章的相关性"""
        if not refined_articles:
            return None
        
        articles_text = ""
        for i, article in enumerate(refined_articles, 1):
            title = article.get("title", "")
            content = article.get("refined_content", "")
            url = article.get("url", "")
            articles_text += f"\n\n文章 {i}:\n标题: {title}\n内容: {content}\n链接: {url}"
        
        prompt = f"""请分析以下所有新闻文章，生成多维度标签和相关性分析：

{articles_text}

要求：
1. 为每篇文章生成多维度标签（主题、事件、人物、地点等）
2. 分析文章之间的相关性，给出相关性分数（0-1，分数越高相关性越高）
3. 说明相关性原因
4. 输出 JSON 格式：
{{
  "article_tags": {{
    "article_1": {{
      "topic": ["标签1", "标签2"],
      "event": ["事件名"],
      "person": ["人物名"],
      "location": ["地点"]
    }}
  }},
  "relationships": [
    {{
      "source_id": "article_1",
      "target_id": "article_2",
      "score": 0.85,
      "tags": ["共同标签"],
      "reason": "相关性原因"
    }}
  ]
}}
"""
        
        messages = [
            {"role": "system", "content": "你是一个专业的新闻分析师，擅长分析新闻的相关性和生成多维度标签。"},
            {"role": "user", "content": prompt}
        ]
        
        response = self.chat_completion(messages, max_tokens=8000)
        if response:
            # 尝试解析 JSON（AI 可能返回带 markdown 代码块的 JSON）
            import json
            import re
            
            # 提取 JSON 部分
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    self.logger.warning("无法解析相关性分析结果为 JSON")
            
            # 如果无法解析，返回原始文本
            return {"raw_response": response}
        
        return None
    
    def generate_wechat_article(self, topic: str, news_contents: List[str]) -> Optional[str]:
        """生成微信文章"""
        if not news_contents:
            return None
        
        contents_text = "\n\n".join([f"新闻 {i+1}:\n{content}" for i, content in enumerate(news_contents)])
        
        prompt = f"""请将以下{topic}相关的新闻整合为一篇用户友好的微信文章：

{contents_text}

要求：
1. 整合为连贯、有逻辑的文章
2. 使用清晰的标题和段落结构
3. 语言通俗易懂，适合普通读者
4. 保留每篇新闻的原文链接
5. 如果新闻数量较多，可以按重要性或相关性组织
6. 使用 HTML 格式输出
"""
        
        messages = [
            {"role": "system", "content": "你是一个专业的微信文章编辑，擅长将多篇新闻整合为用户友好的文章。"},
            {"role": "user", "content": prompt}
        ]
        
        return self.chat_completion(messages, max_tokens=6000)

