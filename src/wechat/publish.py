"""微信草稿发布模块"""
import time
import requests
from typing import List, Dict, Any, Optional
from .auth import WeChatAuth
from ..utils.logger import get_logger


class WeChatPublish:
    """微信发布类"""
    
    def __init__(self, auth: WeChatAuth, config: Dict[str, Any], logger=None):
        """
        初始化发布类
        
        Args:
            auth: 微信认证对象
            config: 微信配置
            logger: 日志记录器
        """
        self.auth = auth
        self.config = config
        self.logger = logger or get_logger()
        self.api_base_url = config.get("api_base_url", "https://api.weixin.qq.com")
    
    def publish_draft(self, media_id: str) -> Optional[Dict[str, Any]]:
        """发布单个草稿"""
        access_token = self.auth.get_access_token()
        if not access_token:
            self.logger.error("无法获取 access_token")
            return None
        
        url = f"{self.api_base_url}/cgi-bin/freepublish/submit"
        params = {"access_token": access_token}
        
        data = {
            "media_id": media_id
        }
        
        try:
            response = requests.post(url, params=params, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if result.get("errcode") == 0:
                self.logger.info(f"草稿发布成功，media_id: {media_id}")
                return {
                    "publish_id": result.get("publish_id"),
                    "msg_data_id": result.get("msg_data_id")
                }
            else:
                error_code = result.get("errcode", "unknown")
                error_msg = result.get("errmsg", "unknown")
                self.logger.error(f"发布草稿失败: {error_code} - {error_msg}")
                return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"发布草稿请求失败: {e}")
            return None
    
    def publish_drafts_batch(self, media_ids: List[str]) -> List[Dict[str, Any]]:
        """批量发布草稿（顺序执行）"""
        self.logger.info(f"开始批量发布 {len(media_ids)} 个草稿")
        
        results = []
        for media_id in media_ids:
            if not media_id:
                continue
            
            result = self.publish_draft(media_id)
            results.append({
                "media_id": media_id,
                "success": result is not None,
                "publish_id": result.get("publish_id") if result else None
            })
            
            # 延迟，避免请求过快
            time.sleep(1)
        
        success_count = sum(1 for r in results if r["success"])
        self.logger.info(f"批量发布完成，成功 {success_count}/{len(media_ids)} 个")
        
        return results

