"""去重处理模块"""
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Set


class Deduplicator:
    """按天去重处理器"""
    
    def __init__(self, date: str = None):
        """
        初始化去重器
        
        Args:
            date: 日期字符串，格式 YYYY-MM-DD，如果为 None 则使用今天
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        self.date = date
        self.file_path = Path(f"data/processed_articles_{date}.json")
        self.processed_urls: Set[str] = set()
        self.lock = threading.Lock()
        self._load()
    
    def _load(self):
        """从文件加载已处理的 URL"""
        if self.file_path.exists():
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    urls = json.load(f)
                    self.processed_urls = set(urls)
            except (json.JSONDecodeError, IOError) as e:
                # 如果文件损坏，重新开始
                self.processed_urls = set()
    
    def is_processed(self, url: str) -> bool:
        """检查 URL 是否已处理"""
        with self.lock:
            return url in self.processed_urls
    
    def mark_processed(self, url: str):
        """标记 URL 为已处理"""
        with self.lock:
            self.processed_urls.add(url)
    
    def save(self):
        """保存去重记录到文件"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with self.lock:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(list(self.processed_urls), f, ensure_ascii=False, indent=2)

