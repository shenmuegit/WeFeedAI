"""微信 access_token 管理"""
import time
import requests
from typing import Optional, Dict, Any
from ..utils.logger import get_logger


class WeChatAuth:
    """微信认证类"""
    
    def __init__(self, config: Dict[str, Any], logger=None):
        """
        初始化认证类
        
        Args:
            config: 微信配置
            logger: 日志记录器
        """
        self.config = config
        self.logger = logger or get_logger()
        self.app_id = config.get("app_id", "")
        self.app_secret = config.get("app_secret", "")
        self.api_base_url = config.get("api_base_url", "https://api.weixin.qq.com")
        
        self._access_token = None
        self._token_expires_at = 0
    
    def get_access_token(self) -> Optional[str]:
        """获取 access_token"""
        # 检查缓存的 token 是否有效
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        
        # 刷新 token
        return self.refresh_access_token()
    
    def refresh_access_token(self) -> Optional[str]:
        """刷新 access_token"""
        url = f"{self.api_base_url}/cgi-bin/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if "access_token" in data:
                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 7200)
                # 提前 5 分钟过期，避免边界情况
                self._token_expires_at = time.time() + expires_in - 300
                self.logger.info("access_token 获取成功")
                return self._access_token
            else:
                error_code = data.get("errcode", "unknown")
                error_msg = data.get("errmsg", "unknown")
                self.logger.error(f"获取 access_token 失败: {error_code} - {error_msg}")
                return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"获取 access_token 请求失败: {e}")
            return None
    
    def is_token_valid(self) -> bool:
        """检查 token 是否有效"""
        return self._access_token is not None and time.time() < self._token_expires_at

