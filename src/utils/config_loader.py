"""配置加载模块"""
import os
import yaml
from typing import Dict, Any
from pathlib import Path


def _replace_env_vars(value: str) -> str:
    """替换环境变量"""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        return os.getenv(env_var, value)
    return value


def _process_dict(data: Dict) -> Dict:
    """递归处理字典，替换环境变量"""
    if isinstance(data, dict):
        return {k: _process_dict(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_process_dict(item) for item in data]
    elif isinstance(data, str):
        return _replace_env_vars(data)
    return data


def load_config(config_path: str = "config/config.yaml") -> Dict[str, Any]:
    """加载主配置文件"""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    return _process_dict(config)


def load_selectors(selectors_path: str = "config/selectors.yaml") -> Dict[str, Any]:
    """加载选择器配置"""
    selectors_file = Path(selectors_path)
    if not selectors_file.exists():
        raise FileNotFoundError(f"选择器配置文件不存在: {selectors_path}")
    
    with open(selectors_file, 'r', encoding='utf-8') as f:
        selectors = yaml.safe_load(f)
    
    return selectors


def get_crawler_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """获取爬取配置"""
    return config.get("crawler", {})


def get_ai_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """获取 AI 配置"""
    return config.get("ai", {})


def get_wechat_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """获取微信配置"""
    return config.get("wechat", {})


def get_scheduler_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """获取定时任务配置"""
    return config.get("scheduler", {})


def get_logging_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """获取日志配置"""
    return config.get("logging", {})


def get_topics_config(config: Dict[str, Any]) -> list:
    """获取主题配置"""
    return config.get("topics", [])

