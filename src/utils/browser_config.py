"""浏览器配置工具"""
from typing import Dict, Any, Optional


def get_browser_context_options(
    storage_state: Optional[str] = None,
    proxy: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取浏览器上下文配置选项
    
    Args:
        storage_state: Session 状态文件路径
        proxy: 代理地址，格式: "http://127.0.0.1:1080"
    
    Returns:
        浏览器上下文配置字典
    """
    context_options = {
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
        'viewport': {'width': 1920, 'height': 1080},
        'locale': 'en-US',
        'timezone_id': 'America/New_York',
        'permissions': ['geolocation'],
        'extra_http_headers': {
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
    }
    
    # 添加代理
    if proxy:
        context_options['proxy'] = {
            'server': proxy
        }
    
    # 添加 session 状态
    if storage_state:
        context_options['storage_state'] = storage_state
    
    return context_options


def get_anti_detection_script() -> str:
    """
    获取反检测 JavaScript 脚本
    注意：此脚本只修改 navigator 属性，不会影响 DOM 事件和用户交互
    延迟执行以确保不影响页面正常功能
    参考: https://carljin.com/%E5%A6%82%E4%BD%95%E4%BD%BF%E7%94%A8-playwright-%E7%99%BB%E5%85%A5-google-%E8%B4%A6%E5%8F%B7/
    
    Returns:
        JavaScript 代码字符串
    """
    return """
        (function() {
            // 只在页面加载时执行一次，避免重复执行
            if (window.__playwright_anti_detection_applied) {
                return;
            }
            
            // 延迟执行，确保不影响页面初始化和事件处理
            // 使用 requestIdleCallback 或 setTimeout 确保在页面稳定后执行
            const applyAntiDetection = () => {
                try {
                    window.__playwright_anti_detection_applied = true;
                    
                    // 移除 webdriver 特征
                    try {
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined,
                            configurable: true,
                            enumerable: false
                        });
                    } catch(e) {
                        console.warn('Failed to remove webdriver property:', e);
                    }
                    
                    // 覆盖 plugins（仅在需要时）
                    try {
                        const originalPlugins = navigator.plugins;
                        if (originalPlugins && originalPlugins.length === 0) {
                            Object.defineProperty(navigator, 'plugins', {
                                get: () => {
                                    const fakePlugins = [];
                                    for (let i = 0; i < 5; i++) {
                                        fakePlugins.push({ name: `Plugin ${i}` });
                                    }
                                    return fakePlugins;
                                },
                                configurable: true,
                                enumerable: false
                            });
                        }
                    } catch(e) {
                        console.warn('Failed to override plugins:', e);
                    }
                    
                    // 覆盖 languages
                    try {
                        Object.defineProperty(navigator, 'languages', {
                            get: () => ['en-US', 'en'],
                            configurable: true,
                            enumerable: false
                        });
                    } catch(e) {
                        console.warn('Failed to override languages:', e);
                    }
                    
                    // 覆盖 permissions（谨慎处理，避免影响正常功能）
                    try {
                        const originalQuery = window.navigator.permissions.query;
                        if (originalQuery) {
                            window.navigator.permissions.query = function(parameters) {
                                // 只处理特定情况，其他情况使用原始方法
                                if (parameters && parameters.name === 'notifications') {
                                    return Promise.resolve({ state: Notification.permission || 'default' });
                                }
                                return originalQuery.call(this, parameters);
                            };
                        }
                    } catch(e) {
                        console.warn('Failed to override permissions:', e);
                    }
                    
                    // Chrome 特征
                    if (!window.chrome) {
                        window.chrome = {
                            runtime: {}
                        };
                    }
                } catch(e) {
                    console.warn('Anti-detection script error:', e);
                }
            };
            
            // 优先使用 requestIdleCallback，否则使用 setTimeout
            if (window.requestIdleCallback) {
                window.requestIdleCallback(applyAntiDetection, { timeout: 1000 });
            } else {
                setTimeout(applyAntiDetection, 500);
            }
        })();
    """


def get_browser_launch_args() -> list:
    """
    获取浏览器启动参数
    参考: https://carljin.com/%E5%A6%82%E4%BD%95%E4%BD%BF%E7%94%A8-playwright-%E7%99%BB%E5%85%A5-google-%E8%B4%A6%E5%8F%B7/
    
    Returns:
        启动参数列表
    """
    return [
        '--disable-blink-features=AutomationControlled',
        '--no-sandbox',
        '--disable-web-security',
        '--disable-infobars',
        '--disable-extensions',
        '--start-maximized',
        '--window-size=1680,930',
        '--disable-features=IsolateOrigins,site-per-process',
        '--disable-notifications',
        '--disable-no-sandbox',
        '--disable-dev-shm-usage',
        '--aggressive-cache-discard',
        '--disable-cache',
        '--disable-application-cache',
        '--disable-offline-load-stale-cache',
        '--disable-gpu-shader-disk-cache',
        '--media-cache-size=0',
        '--disk-cache-size=0',
        '--disable-component-extensions-with-background-pages',
        '--disable-default-apps',
        '--mute-audio',
        '--no-default-browser-check',
        '--autoplay-policy=user-gesture-required',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-background-networking',
        '--disable-search-engine-choice-screen',
        '--disable-breakpad',
        '--disable-component-update',
        '--disable-domain-reliability',
        '--disable-sync',
        '--disable-translate',
    ]

