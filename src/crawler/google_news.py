"""Google News 爬取模块"""
import asyncio
import sys
import re
import threading
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Page, BrowserContext

# 处理导入：支持直接运行和作为模块导入
try:
    # 尝试相对导入（作为模块导入时）
    from ..utils.config_loader import load_selectors, load_config
    from ..utils.logger import get_logger
    from ..utils.browser_config import get_browser_context_options, get_anti_detection_script, get_browser_launch_args
except ImportError:
    # 相对导入失败，使用绝对导入（直接运行时）
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))
    from src.utils.config_loader import load_selectors, load_config
    from src.utils.logger import get_logger
    from src.utils.browser_config import get_browser_context_options, get_anti_detection_script, get_browser_launch_args


class GoogleNewsCrawler:
    """Google News 爬取类"""
    _missing_domain_lock = threading.Lock()

    def __init__(self, config: Dict[str, Any], selectors: Dict[str, Any], logger=None):
        """
        初始化爬取器
        
        Args:
            config: 爬取配置
            selectors: 选择器配置
            logger: 日志记录器
        """
        self.config = config
        self.selectors = selectors
        self.logger = logger or get_logger()
        self.session_file = config.get("session_file", "data/session_state.json")
        self.google_news_url = config.get("google_news_url", "https://news.google.com/home?hl=en-US&gl=US&ceid=US%3Aen")
        self.scroll_wait_time = config.get("scroll_wait_time", 5000)
        self.max_scroll_attempts = config.get("max_scroll_attempts", 50)
        self.request_delay = config.get("request_delay", 1)
        self.proxy = config.get("proxy", None)
    
    async def check_login(self, page: Page) -> bool:
        """检查登录状态"""
        try:
            # 检查是否有登录按钮或提示
            sign_in_elements = await page.locator("text=Sign in").count()
            if sign_in_elements > 0:
                self.logger.warning("检测到未登录状态")
                return False
            return True
        except Exception as e:
            self.logger.error(f"检查登录状态失败: {e}")
            return False
    
    def _locate_element(self, page: Page, selector_config: Dict[str, Any], base_element: Optional[Any] = None):
        """根据配置定位元素"""
        method = selector_config.get("method", "")
        value = selector_config.get("value", "")
        
        if not method or not value:
            return None
        
        # 确定基础元素
        if base_element:
            locator = base_element
        else:
            locator = page
        
        # 根据方法定位
        if method == "text":
            return locator.get_by_text(value).first if hasattr(locator, 'get_by_text') else page.get_by_text(value).first
        elif method == "xpath":
            if base_element:
                return base_element.locator(f"xpath={value}")
            else:
                return page.locator(f"xpath={value}")
        elif method == "tagpath":
            # 使用标签路径定位（从根节点开始）
            # 格式：html.body.div.section.article 或 html.body.div[2].section
            # 将标签路径转换为 XPath 进行定位
            parts = value.split('.')
            xpath_parts = []
            
            for part in parts:
                # 处理带索引的标签，如 div[2]
                if '[' in part and ']' in part:
                    tag, index = part.split('[')
                    index = index.rstrip(']')
                    xpath_parts.append(f"{tag}[{index}]")
                else:
                    xpath_parts.append(part)
            
            # 构建 XPath：从根节点开始
            xpath = "//" + "//".join(xpath_parts[1:]) if len(xpath_parts) > 1 else f"//{xpath_parts[0]}"
            
            if base_element:
                return base_element.locator(f"xpath={xpath}")
            else:
                return page.locator(f"xpath={xpath}")
        elif method == "css":
            # CSS 选择器（已弃用，但保留兼容性）
            if base_element:
                return base_element.locator(value)
            else:
                return page.locator(value)
        elif method == "role":
            return locator.get_by_role(value).first if hasattr(locator, 'get_by_role') else page.get_by_role(value).first
        
        return None
    
    async def get_topic_links(self, page: Page) -> List[Dict[str, str]]:
        """获取所有主题链接"""
        self.logger.info("开始获取主题链接")
        
        topic_links_config = self.selectors.get("home_page", {}).get("topic_links", [])
        if not topic_links_config or not isinstance(topic_links_config, list):
            self.logger.error("未找到主题链接选择器配置或配置格式不正确")
            return []
        
        links = []
        try:
            # 遍历列表中的每个主题配置
            for topic_config in topic_links_config:
                try:
                    topic_name = topic_config.get("name", "")
                    method = topic_config.get("method", "")
                    value = topic_config.get("value", "")
                    
                    if not method or not value:
                        self.logger.warning(f"主题 {topic_name} 的配置不完整，跳过")
                        continue
                    
                    # 根据方法定位元素
                    if method == "xpath":
                        # 使用 xpath 定位单个元素
                        element = page.locator(f"xpath={value}")
                        if await element.count() > 0:
                            href = await element.get_attribute("href")
                            if href:
                                # 处理相对 URL
                                if href.startswith("/"):
                                    href = f"https://news.google.com{href}"
                                elif not href.startswith("http"):
                                    href = f"https://news.google.com/{href}"
                                
                                # 获取文本内容（如果配置中没有名称，使用元素文本）
                                text = await element.text_content()
                                name = topic_name or text or ""
                                
                                links.append({"name": name, "url": href})
                                self.logger.debug(f"找到主题链接: {name} -> {href}")
                            else:
                                self.logger.warning(f"主题 {topic_name} 的链接元素没有 href 属性")
                        else:
                            self.logger.warning(f"主题 {topic_name} 的链接元素未找到 (xpath: {value})")
                    elif method == "text":
                        # 对于文本定位，找到包含该文本的链接
                        elements = await page.get_by_text(value).all()
                        for element in elements:
                            link_element = element.locator("xpath=ancestor::a")
                            if await link_element.count() > 0:
                                href = await link_element.get_attribute("href")
                                if href:
                                    # 处理相对 URL
                                    if href.startswith("/"):
                                        href = f"https://news.google.com{href}"
                                    elif not href.startswith("http"):
                                        href = f"https://news.google.com/{href}"
                                    
                                    text = await link_element.text_content()
                                    name = topic_name or text or value
                                    
                                    links.append({"name": name, "url": href})
                                    self.logger.debug(f"找到主题链接: {name} -> {href}")
                                    break  # 只取第一个匹配的链接
                    else:
                        # 其他定位方法
                        element = page.locator(value)
                        if await element.count() > 0:
                            href = await element.get_attribute("href")
                            if href:
                                # 处理相对 URL
                                if href.startswith("/"):
                                    href = f"https://news.google.com{href}"
                                elif not href.startswith("http"):
                                    href = f"https://news.google.com/{href}"
                                
                                text = await element.text_content()
                                name = topic_name or text or ""
                                
                                links.append({"name": name, "url": href})
                                self.logger.debug(f"找到主题链接: {name} -> {href}")
                except Exception as e:
                    self.logger.warning(f"获取主题 {topic_config.get('name', '未知')} 的链接失败: {e}")
                    continue
            
            self.logger.info(f"找到 {len(links)} 个主题链接")
            return links
        except Exception as e:
            self.logger.error(f"获取主题链接失败: {e}")
            return []
    
    def _modify_xpath_index(self, xpath: str, target_index: int, position: int = -1) -> str:
        """修改 XPath 中指定位置的索引
        
        Args:
            xpath: 原始 XPath 字符串
            target_index: 目标索引（从1开始）
            position: 要修改的位置（-1 表示最后一个，-2 表示倒数第二个，以此类推）
            
        Returns:
            修改后的 XPath 字符串
        """
        # 使用正则表达式匹配所有带索引的标签，如 c-wiz[1]
        pattern = r'(\w+(?:-\w+)*)\[(\d+)\]'
        matches = list(re.finditer(pattern, xpath))
        
        if not matches:
            return xpath
        
        # 根据 position 确定要修改的匹配项
        if position < 0:
            # 负数表示从后往前数
            target_match_idx = len(matches) + position
        else:
            # 正数表示从前往后数（从0开始）
            target_match_idx = position
        
        if target_match_idx < 0 or target_match_idx >= len(matches):
            return xpath
        
        # 替换指定位置的索引
        match = matches[target_match_idx]
        tag_name = match.group(1)
        new_xpath = xpath[:match.start()] + f"{tag_name}[{target_index}]" + xpath[match.end():]
        return new_xpath
    
    def _get_xpath_evaluator_script(self) -> str:
        """获取 XPath 评估器的 JavaScript 代码（只注入一次）"""
        return """
        // 全局 XPath 评估函数，只注入一次
        if (!window.__wefeedai_xpath_evaluator) {
            window.__wefeedai_xpath_evaluator = function(xpath) {
                try {
                    const result = document.evaluate(
                        xpath,
                        document,
                        null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE,
                        null
                    );
                    const element = result.singleNodeValue;
                    if (element) {
                        const href = element.href || element.getAttribute('href') || '';
                        return { found: true, href: href };
                    } else {
                        return { found: false, reason: 'link_not_found' };
                    }
                } catch(e) {
                    return { found: false, reason: 'error', error: e.message };
                }
            };
        }
        """
    
    async def _get_news_container_count(self, page: Page, news_container_config: Dict[str, Any]) -> int:
        """获取新闻容器的数量（直接使用 XPath，不使用相对定位）"""
        method = news_container_config.get("method", "xpath")
        value = news_container_config.get("value", "")
        
        if method == "xpath":
            # 提取父元素 XPath（去掉末尾的 /*）
            parent_xpath = value.rstrip("/*")
            if not parent_xpath:
                parent_xpath = value
            
            # 使用 JavaScript 获取子元素数量
            count = await page.evaluate("""
                (parentXPath) => {
                    try {
                        const result = document.evaluate(
                            parentXPath,
                            document,
                            null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE,
                            null
                        );
                        const parent = result.singleNodeValue;
                        if (parent && parent.children) {
                            return parent.children.length;
                        }
                        return 0;
                    } catch(e) {
                        console.error('获取新闻容器数量失败:', e);
                        return 0;
                    }
                }
            """, parent_xpath)
            
            return count if count else 0
        else:
            self.logger.warning(f"不支持的定位方法: {method}")
            return 0
    
    async def _get_children_locator(self, page: Page, news_container_config: Dict[str, Any]):
        """获取新闻容器的子元素定位器
        
        Args:
            page: Playwright 页面对象
            news_container_config: 新闻容器配置（指向父元素）
            
        Returns:
            Locator 对象，定位到父元素的所有直接子元素
        """
        method = news_container_config.get("method", "xpath")
        value = news_container_config.get("value", "")
        
        self.logger.debug(f"获取子元素定位器 - method: {method}, value: {value}")
        
        if method == "xpath":
            # 使用 JavaScript 的 document.evaluate 定位父元素，然后获取子元素
            self.logger.debug(f"XPath 查找 - 原始值: {value}")
            
            # 提取父元素 XPath
            parent_xpath = value
            if value.endswith("/*"):
                parent_xpath = value[:-2]
            
            # 使用 JavaScript 注入查找父元素并获取其 XPath
            result = await page.evaluate("""
                (parentXPath) => {
                    try {
                        console.log('[DEBUG _get_children_locator] 执行 document.evaluate，XPath:', parentXPath);
                        
                        // 使用 document.evaluate 查找父元素
                        const parentResult = document.evaluate(
                            parentXPath,
                            document,
                            null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE,
                            null
                        );
                        
                        let parent = parentResult.singleNodeValue;
                        
                        if (!parent) {
                            return { found: false, reason: 'parent_not_found' };
                        }
                        
                        // 生成父元素的 XPath
                        function getXPath(element) {
                            if (!element || element.nodeType !== 1) {
                                return '';
                            }
                            if (element === document.documentElement) {
                                return '/html';
                            }
                            if (element === document.body) {
                                return '/html/body';
                            }
                            if (!element.parentNode) {
                                return '';
                            }
                            let ix = 0;
                            const siblings = element.parentNode.childNodes;
                            for (let i = 0; i < siblings.length; i++) {
                                const sibling = siblings[i];
                                if (sibling === element) {
                                    const parentPath = getXPath(element.parentNode);
                                    if (!parentPath) {
                                        return '';
                                    }
                                    return parentPath + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
                                }
                                if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {
                                    ix++;
                                }
                            }
                            return '';
                        }
                        
                        const parentXPathGenerated = getXPath(parent);
                        const childrenCount = parent.children ? parent.children.length : 0;
                        
                        console.log('[DEBUG _get_children_locator] ✓ 找到父元素');
                        console.log('[DEBUG _get_children_locator] 父元素标签:', parent.tagName);
                        console.log('[DEBUG _get_children_locator] 父元素子元素数量:', childrenCount);
                        
                        return {
                            found: true,
                            parentXPath: parentXPathGenerated,
                            childrenCount: childrenCount,
                            parentTag: parent.tagName
                        };
                    } catch(e) {
                        console.error('[DEBUG _get_children_locator] 错误:', e);
                        return { found: false, reason: 'error', error: e.message };
                    }
                }
            """, parent_xpath)
            
            if result and result.get('found'):
                parent_xpath_generated = result.get('parentXPath', '')
                children_count = result.get('childrenCount', 0)
                parent_tag = result.get('parentTag', '')
                
                self.logger.debug(f"XPath 查找成功 - 父元素 XPath: {parent_xpath_generated}")
                self.logger.debug(f"XPath 查找成功 - 父元素标签: {parent_tag}")
                self.logger.debug(f"XPath 查找成功 - 子元素数量: {children_count}")
                
                if parent_xpath_generated:
                    # 使用父元素的 XPath + /* 来获取所有直接子元素
                    child_xpath = parent_xpath_generated + "/*"
                    return page.locator(f"xpath={child_xpath}")
                else:
                    self.logger.error("XPath 找到元素但无法生成 XPath")
                    return None
            else:
                self.logger.error(f"XPath 查找失败: {result.get('reason', 'unknown')}")
                return None
        elif method == "tagpath":
            # 对于 tagpath，使用 JavaScript 注入来查找父元素（参考 selector_helper.py）
            # 这样可以避免 XPath 转换的问题
            self.logger.debug(f"TagPath 查找 - 原始值: {value}")
            
            # 使用 JavaScript 注入查找父元素并获取其 XPath
            # 方法：直接在 JS 中解析 tagpath，找到最后一个标签元素，然后通过 JS 获取父元素
            result = await page.evaluate("""
                (tagPath) => {
                    const parts = tagPath.split('.');
                    
                    if (parts.length === 0) {
                        return { found: false, reason: 'empty_tagpath' };
                    }
                    
                    // 解析 tagpath，逐步查找元素
                    let elements = [document];
                    
                    for (let i = 0; i < parts.length; i++) {
                        const part = parts[i];
                        const match = part.match(/^(\\w+(?:-\\w+)*)(?:\\[(\\d+)\\])?$/);
                        if (!match) continue;
                        
                        const tagName = match[1];
                        const index = match[2] ? parseInt(match[2]) - 1 : null;
                        const nextElements = [];
                        
                        for (const parent of elements) {
                            let children = [];
                            
                            if (index !== null) {
                                // 有索引时，在所有后代元素中查找（用于精确定位，如 c-wiz[2]）
                                children = Array.from(parent.getElementsByTagName(tagName));
                                // 只选择指定索引的元素
                                if (children[index]) {
                                    nextElements.push(children[index]);
                                }
                            } else {
                                // 没有索引时，只在直接子元素中查找（路径语义）
                                let allChildren = [];
                                if (parent === document || parent === document.documentElement) {
                                    // document 的特殊处理
                                    if (parent === document) {
                                        allChildren = document.documentElement ? [document.documentElement] : [];
                                    } else {
                                        allChildren = Array.from(parent.children || []);
                                    }
                                } else {
                                    allChildren = Array.from(parent.children || []);
                                }
                                children = allChildren.filter(child => child.tagName.toLowerCase() === tagName.toLowerCase());
                                // 选择所有匹配的直接子元素
                                nextElements.push(...children);
                            }
                        }
                        
                        elements = nextElements;
                    }
                    
                    // elements 现在包含所有最后一个标签的元素
                    if (elements.length === 0) {
                        return { found: false, reason: 'last_tag_not_found' };
                    }
                    
                    // 找到所有最后一个标签元素的父元素，选择有最多子元素的父元素
                    let bestParent = null;
                    let maxChildren = 0;
                    
                    for (let i = 0; i < elements.length; i++) {
                        const lastTagElement = elements[i];
                        if (!lastTagElement || !lastTagElement.parentElement) {
                            continue;
                        }
                        
                        const candidateParent = lastTagElement.parentElement;
                        const childCount = (candidateParent.children || []).length;
                        
                        if (childCount > maxChildren) {
                            maxChildren = childCount;
                            bestParent = candidateParent;
                        }
                    }
                    
                    if (!bestParent) {
                        return { found: false, reason: 'parent_not_found' };
                    }
                    
                    // 生成父元素的 XPath
                    function getXPath(element) {
                        if (!element || element.nodeType !== 1) {
                            return '';
                        }
                        if (element === document.documentElement) {
                            return '/html';
                        }
                        if (element === document.body) {
                            return '/html/body';
                        }
                        if (!element.parentNode) {
                            return '';
                        }
                        let ix = 0;
                        const siblings = element.parentNode.childNodes;
                        for (let i = 0; i < siblings.length; i++) {
                            const sibling = siblings[i];
                            if (sibling === element) {
                                const parentPath = getXPath(element.parentNode);
                                if (!parentPath) {
                                    return '';
                                }
                                return parentPath + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
                            }
                            if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {
                                ix++;
                            }
                        }
                        return '';
                    }
                    
                    const parentXPath = getXPath(bestParent);
                    const childrenCount = bestParent.children ? bestParent.children.length : 0;
                    
                    return {
                        found: true,
                        parentXPath: parentXPath,
                        childrenCount: childrenCount,
                        parentTag: bestParent.tagName
                    };
                }
            """, value)
            
            if result and result.get('found'):
                parent_xpath = result.get('parentXPath', '')
                children_count = result.get('childrenCount', 0)
                parent_tag = result.get('parentTag', '')
                
                self.logger.debug(f"TagPath 查找成功 - 父元素 XPath: {parent_xpath}")
                self.logger.debug(f"TagPath 查找成功 - 父元素标签: {parent_tag}")
                self.logger.debug(f"TagPath 查找成功 - 子元素数量: {children_count}")
                
                if parent_xpath:
                    # 使用父元素的 XPath + /* 来获取所有直接子元素
                    child_xpath = parent_xpath + "/*"
                    return page.locator(f"xpath={child_xpath}")
                else:
                    self.logger.error("TagPath 找到元素但无法生成 XPath")
                    return None
            else:
                self.logger.error(f"TagPath 查找失败: {result.get('reason', 'unknown')}")
                return None
        else:
            # 其他方法，先定位父元素，然后获取子元素
            parent_locator = self._locate_element(page, news_container_config)
            if not parent_locator:
                return None
            # 返回一个可以获取子元素的 locator
            self.logger.warning(f"不支持的定位方法 {method}，尝试使用父元素定位器")
            return parent_locator.locator("xpath=./*")
    
    async def scroll_and_load_more(self, page: Page) -> int:
        """滚动加载更多新闻
        
        参考 selector_helper.py 中的 scrollToBottomUntilNoNewContent 函数
        先使用 JavaScript 注入滚动到底部获取全部 HTML，然后再定位
        """
        self.logger.info("开始滚动加载更多新闻")
        
        topic_config = self.selectors.get("topic_page", {})
        news_container_config = topic_config.get("news_container", {})
        
        if not news_container_config:
            self.logger.warning("未找到新闻容器选择器配置，跳过滚动")
            return 0
        
        method = news_container_config.get("method", "xpath")
        value = news_container_config.get("value", "")
        
        if not value:
            self.logger.warning("新闻容器配置值为空，跳过滚动")
            return 0
        
        # 首先注入 scrollToBottomUntilNoNewContent 函数并执行
        self.logger.info("正在滚动到底部，等待所有内容加载...")
        scroll_attempts = await page.evaluate("""
            () => {
                // 参考 selector_helper.py 的 scrollToBottomUntilNoNewContent 函数
                return new Promise(async (resolve) => {
                    let scrollAttempts = 0;
                    const maxAttempts = 100; // 最多尝试100次
                    let lastHeight = 0;
                    let lastRequestTime = Date.now();
                    let noChangeCount = 0; // 连续没有变化的次数
                    const requiredNoChangeCount = 3; // 需要连续3次没有变化才停止
                    const waitTime = 2000; // 每次等待2秒
                    
                    // 监听网络请求（通过 Performance API）
                    let activeRequests = 0;
                    const observer = new PerformanceObserver((list) => {
                        for (const entry of list.getEntries()) {
                            if (entry.entryType === 'resource') {
                                activeRequests++;
                                lastRequestTime = Date.now();
                            }
                        }
                    });
                    observer.observe({ entryTypes: ['resource'] });
                    
                    // 也监听 fetch 和 XHR
                    const originalFetch = window.fetch;
                    const originalXHR = window.XMLHttpRequest;
                    let fetchCount = 0;
                    let xhrCount = 0;
                    
                    window.fetch = function(...args) {
                        fetchCount++;
                        lastRequestTime = Date.now();
                        return originalFetch.apply(this, args);
                    };
                    
                    const xhrOpen = originalXHR.prototype.open;
                    originalXHR.prototype.open = function(...args) {
                        xhrCount++;
                        lastRequestTime = Date.now();
                        return xhrOpen.apply(this, args);
                    };
                    
                    while (scrollAttempts < maxAttempts) {
                        // 滚动到底部
                        const currentHeight = document.documentElement.scrollHeight;
                        window.scrollTo(0, currentHeight);
                        
                        // 等待一段时间让请求完成
                        await new Promise(r => setTimeout(r, waitTime));
                        
                        // 检查页面高度和网络请求
                        const newHeight = document.documentElement.scrollHeight;
                        const timeSinceLastRequest = Date.now() - lastRequestTime;
                        const hasNewContent = (newHeight !== lastHeight);
                        const hasRecentRequests = (timeSinceLastRequest < waitTime * 2);
                        
                        if (!hasNewContent && !hasRecentRequests) {
                            noChangeCount++;
                            if (noChangeCount >= requiredNoChangeCount) {
                                // 恢复原始函数和观察者
                                window.fetch = originalFetch;
                                originalXHR.prototype.open = xhrOpen;
                                observer.disconnect();
                                resolve(scrollAttempts);
                                return;
                            }
                        } else {
                            noChangeCount = 0;
                        }
                        
                        lastHeight = newHeight;
                        scrollAttempts++;
                    }
                    
                    // 恢复原始函数和观察者
                    window.fetch = originalFetch;
                    originalXHR.prototype.open = xhrOpen;
                    observer.disconnect();
                    resolve(scrollAttempts);
                });
            }
        """)
        
        self.logger.info(f"滚动完成，共尝试 {scroll_attempts} 次")
        
        # 滚动完成后，获取最终的新闻容器数量
        final_count = await self._get_news_container_count(page, news_container_config)
        self.logger.info(f"滚动完成后，共找到 {final_count} 个新闻容器")
        
        return final_count
    
    async def extract_news_items(self, page: Page) -> List[Dict[str, Any]]:
        """提取新闻项（优化版：使用绝对 XPath，根据索引修改）"""
        topic_config = self.selectors.get("topic_page", {})
        news_container_config = topic_config.get("news_container", {})
        sources_config = topic_config.get("sources", [])
        
        if not news_container_config:
            self.logger.error("未找到新闻容器选择器配置")
            return []
        
        try:
            # 获取新闻容器数量（不使用相对定位）
            item_count = await self._get_news_container_count(page, news_container_config)
            self.logger.info(f"找到 {item_count} 个新闻项")
            
            if item_count == 0:
                self.logger.warning("未找到任何新闻项")
                return []
            
            articles = []
            for idx in range(1, item_count + 1):
                try:
                    self.logger.info(f"正在提取第 {idx}/{item_count} 个新闻项的信息")
                    # 根据索引修改 sources_config 中的 XPath
                    modified_sources_config = self._modify_sources_config_for_index(sources_config, idx)
                    article_info = await self.extract_news_info_by_index(page, idx, modified_sources_config)
                    if article_info:
                        articles.append(article_info)
                        self.logger.info(f"✓ 成功提取第 {idx} 个新闻项，来源数量: {len(article_info.get('sources', []))}")
                    else:
                        self.logger.warning(f"⚠️ 第 {idx} 个新闻项未提取到有效信息（可能没有来源）")
                except Exception as e:
                    self.logger.error(f"提取第 {idx} 个新闻信息失败: {e}")
                    import traceback
                    self.logger.debug(traceback.format_exc())
                    continue
            
            return articles
        except Exception as e:
            self.logger.error(f"提取新闻项失败: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return []
    
    def _modify_sources_config_for_index(self, sources_config: List[Dict[str, Any]], news_index: int) -> List[Dict[str, Any]]:
        """根据新闻项索引修改 sources_config 中的 XPath
        
        Args:
            sources_config: 原始来源配置列表
            news_index: 新闻项索引（从1开始）
            
        Returns:
            修改后的来源配置列表
        """
        modified_config = []
        for source_config in sources_config:
            modified_source = source_config.copy()
            link_config = source_config.get("link", {})
            if link_config:
                modified_link = link_config.copy()
                link_value = link_config.get("value", "")
                if link_value and isinstance(link_value, str):
                    # 根据配置文件，新闻容器路径是：/html/body/c-wiz[1]/div[1]/main[1]/c-wiz[1]/c-wiz[1]
                    # 来源 XPath 在容器路径后是：/c-wiz[1]/c-wiz[1]/div[1]/div[1]/div[1]/div[1]/a[1]
                    # 第一个 c-wiz[1] 是新闻项索引，需要修改
                    # 从完整 XPath 看，这是第6个带索引的元素（从0开始是位置5）
                    # 或者从后往前数，是倒数第7个（-7）
                    modified_link["value"] = self._modify_xpath_index(link_value, news_index, 5)
                modified_source["link"] = modified_link
            modified_config.append(modified_source)
        return modified_config
    
    async def extract_news_info_by_index(
        self,
        page: Page,
        news_index: int,
        sources_config: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """根据索引提取单个新闻信息（不使用 news_item 对象）"""
        article = {}
        
        # 提取来源（最多4个）
        sources = []
        for idx, source_config in enumerate(sources_config[:4], 1):
            try:
                self.logger.debug(f"处理来源配置 {idx}: {source_config}")
                link_config = source_config.get("link", {})
                link_value = link_config.get("value", "")
                
                # 确保 link_value 是字符串
                if not isinstance(link_value, str):
                    self.logger.error(f"来源 {idx} 的 link_value 不是字符串: {type(link_value)}, 值: {link_value}")
                    continue
                
                self.logger.info(f"尝试提取来源 {idx} (XPath: {link_value})")
                source_info = await self.extract_source_info_by_xpath(page, link_value)
                if source_info:
                    sources.append(source_info)
                    self.logger.info(f"✓ 成功提取来源 {idx}: {source_info.get('url', '')}")
                else:
                    # 跳过这个来源，继续提取下一个来源
                    self.logger.warning(f"⚠️ 来源 {idx} 提取失败 (XPath: {link_value or 'N/A'})")
            except Exception as e:
                self.logger.debug(f"提取来源 {idx} 信息失败: {e}")
                import traceback
                self.logger.debug(traceback.format_exc())
                continue
        
        if sources:
            article["sources"] = sources
            self.logger.debug(f"成功提取 {len(sources)} 个来源")
        else:
            self.logger.debug("未提取到任何来源")
        
        # 必须有来源才返回
        if not article.get("sources"):
            return None
        
        return article
    
    async def extract_news_info(
        self,
        page: Page,
        news_item: Any,
        sources_config: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """提取单个新闻信息（保留用于兼容性）"""
        article = {}
        
        # 提取来源（最多4个）
        sources = []
        for idx, source_config in enumerate(sources_config[:4], 1):
            try:
                self.logger.debug(f"处理来源配置 {idx}: {source_config}")
                link_config = source_config.get("link", {})
                self.logger.debug(f"link_config: {link_config}, 类型: {type(link_config)}")
                link_value = link_config.get("value", "")
                self.logger.debug(f"link_value: {link_value}, 类型: {type(link_value)}")
                
                # 确保 link_value 是字符串
                if not isinstance(link_value, str):
                    self.logger.error(f"来源 {idx} 的 link_value 不是字符串: {type(link_value)}, 值: {link_value}")
                    self.logger.error(f"完整的 source_config: {source_config}")
                    continue
                
                self.logger.info(f"尝试提取来源 {idx} (XPath: {link_value})")
                source_info = await self.extract_source_info(page, news_item, source_config)
                if source_info:
                    sources.append(source_info)
                    self.logger.info(f"✓ 成功提取来源 {idx}: {source_info.get('url', '')}")
                else:
                    self.logger.warning(f"⚠️ 来源 {idx} 提取失败 (XPath: {link_value or 'N/A'})")
            except Exception as e:
                self.logger.debug(f"提取来源 {idx} 信息失败: {e}")
                import traceback
                self.logger.debug(traceback.format_exc())
                continue
        
        if sources:
            article["sources"] = sources
            self.logger.debug(f"成功提取 {len(sources)} 个来源")
        else:
            self.logger.debug("未提取到任何来源")
        
        # 必须有来源才返回
        if not article.get("sources"):
            return None
        
        return article
    
    async def extract_source_info_by_xpath(self, page: Page, xpath: str) -> Optional[Dict[str, Any]]:
        """根据 XPath 提取来源信息（使用已注入的全局函数）"""
        if not xpath or not isinstance(xpath, str):
            return None
        
        try:
            # 使用已注入的全局函数（只注入一次）
            link_info = await page.evaluate("""
                (xpath) => {
                    if (window.__wefeedai_xpath_evaluator) {
                        return window.__wefeedai_xpath_evaluator(xpath);
                    } else {
                        // 如果函数未注入，临时执行
                        try {
                            const result = document.evaluate(
                                xpath,
                                document,
                                null,
                                XPathResult.FIRST_ORDERED_NODE_TYPE,
                                null
                            );
                            const element = result.singleNodeValue;
                            if (element) {
                                const href = element.href || element.getAttribute('href') || '';
                                return { found: true, href: href };
                            } else {
                                return { found: false, reason: 'link_not_found' };
                            }
                        } catch(e) {
                            return { found: false, reason: 'error', error: e.message };
                        }
                    }
                }
            """, xpath)
            
            if link_info and link_info.get('found'):
                href = link_info.get('href', '')
                if href:
                    # 处理相对 URL
                    if href.startswith("/"):
                        href = f"https://news.google.com{href}"
                    elif not href.startswith("http"):
                        href = f"https://news.google.com/{href}"
                    self.logger.debug(f"✓ 成功提取来源链接: {href}")
                    return {"url": href}
            else:
                reason = link_info.get('reason', 'unknown') if link_info else 'no_info'
                self.logger.debug(f"未找到链接 (XPath: {xpath}, 原因: {reason})")
                return None
        except Exception as e:
            self.logger.debug(f"提取来源信息失败: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return None
    
    async def extract_source_info(self, page: Page, news_item: Any, source_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """提取单个来源信息（仅提取 URL，保留用于兼容性）"""
        link_config = source_config.get("link", {})
        if not link_config:
            return None
        
        link_method = link_config.get("method", "xpath")
        link_value_raw = link_config.get("value", "")
        self.logger.info(f"link_value_raw: {link_value_raw}")

        try:
            # 定位来源链接
            # 只处理绝对路径的 XPath，使用 document.evaluate 在整个文档中查找，然后检查是否在 news_item 内部
            if link_method == "xpath":
                # 使用新的方法
                return await self.extract_source_info_by_xpath(page, link_value_raw)
            else:
                # 其他方法（tagpath, text等）
                link_element = self._locate_element(page, link_config, base_element=news_item)
                if not link_element:
                    return None
                if await link_element.count() == 0:
                    return None
                href = await link_element.get_attribute("href")
                if not href:
                    return None
                if href.startswith("/"):
                    href = f"https://news.google.com{href}"
                elif not href.startswith("http"):
                    href = f"https://news.google.com/{href}"
                return {"url": href}
        except Exception as e:
            self.logger.debug(f"提取来源信息失败: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return None
    
    def _extract_domain(self, url: str) -> Optional[str]:
        """从 URL 中提取域名"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            # 移除端口号
            if ':' in domain:
                domain = domain.split(':')[0]
            return domain
        except Exception as e:
            self.logger.debug(f"提取域名失败: {e}, URL: {url}")
            return None
    
    def _should_ignore_domain(self, domain: str, url: str) -> bool:
        """检查域名或URL是否应该被忽略（不记录）
        
        Args:
            domain: 域名
            url: 完整的URL
            
        Returns:
            如果应该忽略则返回True，否则返回False
        """
        # 获取排除配置（确保为可迭代列表，避免 YAML 中 null 导致 NoneType 不可迭代）
        exclude_config = self.selectors.get("exclude") or {}
        exclude_domains = exclude_config.get("domains") or []
        exclude_url_patterns = exclude_config.get("url_patterns") or []
        
        # 检查域名是否在排除列表中
        for exclude_domain in exclude_domains:
            if domain == exclude_domain or domain.startswith(exclude_domain):
                return True
        
        # 检查URL是否匹配排除模式
        for pattern in exclude_url_patterns:
            try:
                if re.match(pattern, url):
                    return True
            except re.error:
                # 如果正则表达式无效，记录错误但继续
                self.logger.debug(f"无效的正则表达式模式: {pattern}")
        
        return False
    
    def _record_missing_domain(self, domain: str, url: str):
        """记录未找到配置的域名到本地文件（不包括 news.google.com）
        
        Args:
            domain: 域名
            url: 完整的URL
        """
        try:
            # 检查是否应该忽略
            if self._should_ignore_domain(domain, url):
                return

            with self._missing_domain_lock:
                # 配置文件路径
                config_dir = Path(__file__).parent.parent.parent / "config"
                missing_domains_file = config_dir / "missing_domains.txt"

                # 读取已存在的域名列表
                existing_domains = set()
                if missing_domains_file.exists():
                    with open(missing_domains_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                # 格式可能是: domain 或 domain|url|timestamp
                                if '|' in line:
                                    existing_domain = line.split('|')[0].strip()
                                else:
                                    existing_domain = line
                                existing_domains.add(existing_domain)

                # 如果域名已存在，跳过
                if domain in existing_domains:
                    return

                # 追加新域名到文件
                with open(missing_domains_file, 'a', encoding='utf-8') as f:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"{domain}|{url}|{timestamp}\n")

                self.logger.info(f"已记录未找到配置的域名: {domain} -> {missing_domains_file}")
        except Exception as e:
            self.logger.debug(f"记录未找到域名失败: {e}")
    
    def _record_no_content_domain(self, domain: str, url: str, reason: str = ""):
        """记录已配置但未获取到内容的域名到本地文件
        
        Args:
            domain: 域名
            url: 完整的URL
            reason: 缺失原因（如：title_missing,content_missing,cover_missing）
        """
        try:
            # 检查是否应该忽略
            if self._should_ignore_domain(domain, url):
                return
            
            # 配置文件路径
            config_dir = Path(__file__).parent.parent.parent / "config"
            no_content_domains_file = config_dir / "no_content_domains.txt"
            
            # 读取已存在的记录（使用域名+URL作为唯一标识）
            existing_records = set()
            if no_content_domains_file.exists():
                with open(no_content_domains_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            # 格式：domain|reason|url|timestamp
                            parts = line.split('|')
                            if len(parts) >= 3:
                                record_key = f"{parts[0].strip()}|{parts[2].strip()}"  # domain|url
                                existing_records.add(record_key)
            
            # 如果记录已存在，跳过
            record_key = f"{domain}|{url}"
            if record_key in existing_records:
                return
            
            # 追加新记录到文件（格式：domain|reason|url|timestamp）
            with open(no_content_domains_file, 'a', encoding='utf-8') as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"{domain}|{reason}|{url}|{timestamp}\n")
            
            self.logger.info(f"已记录未获取到内容的域名: {domain} (原因: {reason}) -> {no_content_domains_file}")
        except Exception as e:
            self.logger.debug(f"记录未获取到内容域名失败: {e}")
    
    async def _get_third_party_news(self, context: BrowserContext, url: str) -> Optional[Dict[str, Any]]:
        """获取第三方新闻内容
        
        Args:
            context: 浏览器上下文
            url: 新闻URL（可能是 Google News 的跳转链接）
            
        Returns:
            包含标题、内容、封面的字典，如果失败则返回None
        """
        if not url:
            return None
        
        # 打开新标签页
        new_page = await context.new_page()
        try:
            # 首先访问 Google News 链接，等待重定向
            self.logger.debug(f"正在访问链接（等待重定向）: {url}")
            # 使用 "load" 而不是 "networkidle"，因为有些页面可能持续有网络请求
            for i in range(5):
                try:
                    await new_page.goto(url, wait_until="load", timeout=60000)
                except Exception as e:
                    self.logger.debug(f"页面加载超时，尝试继续: {e}")
                    await asyncio.sleep(1)
                    continue
                # 判断是否发生重定向：新旧地址不同则视为已重定向，退出循环
                if new_page.url != url:
                    self.logger.debug(f"已重定向: {url} -> {new_page.url}")
                    break
                # 地址未变，等待后重试一次（给延迟重定向时间）
                await asyncio.sleep(2)

            # 等待可能的跳转（重定向）
            await asyncio.sleep(3)  # 给重定向一些时间

            # 重定向后等待 dom 就绪，并处理可能发生的二次重定向
            last_url = None
            for _ in range(3):  # 最多处理二次重定向
                for i in range(5):
                    try:
                        await new_page.wait_for_load_state("domcontentloaded", timeout=5000)
                        break
                    except Exception:
                        await asyncio.sleep(1)
                        continue
                # 给二次重定向一点时间（如 meta refresh / JS 跳转）
                await asyncio.sleep(2)
                current_url = new_page.url
                if current_url == last_url:
                    break
                last_url = current_url

            # 获取最终URL（重定向后）
            final_url = new_page.url
            self.logger.debug(f"重定向完成，最终URL: {final_url}")
            
            # 重定向完成后才获取域名
            final_domain = self._extract_domain(final_url)
            if not final_domain:
                self.logger.debug(f"无法提取最终域名，跳过: {final_url}")
                return None
            
            self.logger.debug(f"提取到最终域名: {final_domain}")
            
            # 在配置中查找对应的选择器（使用最终域名）
            third_party_config = self.selectors.get("third_party_news", {})
            # 删除www.
            final_domain = final_domain.replace("www.", "")
            site_config = third_party_config.get(final_domain)
            
            if not site_config:
                self.logger.debug(f"未找到域名 {final_domain} 的配置，跳过")
                # 记录未找到的域名到本地文件
                self._record_missing_domain(final_domain, final_url)
                return None
            
            # 提取标题、内容、封面
            result = {}
            missing_reasons = []  # 记录缺失的原因
            
            # 辅助函数：将 value 转换为数组（支持字符串和数组）
            def normalize_xpath_value(value):
                """将 value 转换为数组，如果是字符串则转为单元素数组"""
                if not value:
                    return []
                if isinstance(value, str):
                    return [value]
                if isinstance(value, list):
                    return value
                return []
            
            # 提取标题
            title_config = site_config.get("title", {})
            if title_config and title_config.get("value"):
                title_xpaths = normalize_xpath_value(title_config.get("value", ""))
                title_found = False
                for idx, title_xpath in enumerate(title_xpaths):
                    if not title_xpath:
                        continue
                    title_info = await new_page.evaluate("""
                        (xpath) => {
                            try {
                                const result = document.evaluate(
                                    xpath,
                                    document,
                                    null,
                                    XPathResult.FIRST_ORDERED_NODE_TYPE,
                                    null
                                );
                                const element = result.singleNodeValue;
                                if (element) {
                                    return { found: true, text: element.textContent || element.innerText || '' };
                                } else {
                                    return { found: false };
                                }
                            } catch(e) {
                                return { found: false, error: e.message };
                            }
                        }
                    """, title_xpath)
                    if title_info and title_info.get('found'):
                        title_text = title_info.get('text', '').strip()
                        if title_text:
                            result['title'] = title_text
                            self.logger.debug(f"✓ 提取标题成功 (XPath {idx+1}/{len(title_xpaths)}): {result['title']}")
                            title_found = True
                            break
                    else:
                        self.logger.debug(f"标题 XPath {idx+1}/{len(title_xpaths)} 未找到元素: {title_xpath} domain: {final_domain}")
                
                if not title_found:
                    if title_xpaths:
                        missing_reasons.append("title_missing")
                    else:
                        missing_reasons.append("title_xpath_not_configured")
            
            # 提取内容
            content_config = site_config.get("content", {})
            if content_config and content_config.get("value"):
                content_xpaths = normalize_xpath_value(content_config.get("value", ""))
                content_found = False
                for idx, content_xpath in enumerate(content_xpaths):
                    if not content_xpath:
                        continue
                    content_info = await new_page.evaluate("""
                        (xpath) => {
                            try {
                                const result = document.evaluate(
                                    xpath,
                                    document,
                                    null,
                                    XPathResult.FIRST_ORDERED_NODE_TYPE,
                                    null
                                );
                                const element = result.singleNodeValue;
                                if (element) {
                                    return { found: true, text: element.textContent || element.innerText || '', html: element.innerHTML || '' };
                                } else {
                                    return { found: false };
                                }
                            } catch(e) {
                                return { found: false, error: e.message };
                            }
                        }
                    """, content_xpath)
                    if content_info and content_info.get('found') and len(content_info.get('text', '').strip()) > 300:
                        content_text = content_info.get('text', '').strip()
                        if content_text:
                            result['content'] = content_text
                            result['content_html'] = content_info.get('html', '').strip()
                            self.logger.debug(f"✓ 提取内容成功 (XPath {idx+1}/{len(content_xpaths)})，长度: {len(result['content'])}")
                            content_found = True
                            break
                    else:
                        self.logger.debug(f"内容 XPath {idx+1}/{len(content_xpaths)} 未找到元素: {content_xpath} domain: {final_domain}")
                
                if not content_found:
                    if content_xpaths:
                        missing_reasons.append("content_missing")
                        # 存在 xpath 但未正确提取时，将页面完整 HTML 保存到本地便于排查
                        try:
                            html_dir = Path(__file__).parent.parent.parent / "debug_html"
                            html_dir.mkdir(parents=True, exist_ok=True)
                            safe_domain = "".join(c for c in final_domain if c.isalnum() or c in ('.', '-', '_'))[:64]
                            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filepath = html_dir / f"{safe_domain}_{ts}.html"
                            html_content = await new_page.content()
                            filepath.write_text(html_content, encoding='utf-8')
                            self.logger.debug(f"内容未提取，已保存页面 HTML: {filepath}")
                        except Exception as e:
                            self.logger.debug(f"保存页面 HTML 失败: {e}")
                    else:
                        missing_reasons.append("content_xpath_not_configured")

            # 如果有任何缺失，记录到文件（但只有封面缺失的情况不记录）
            if missing_reasons:
                # 过滤掉只有封面缺失的情况
                important_missing = [
                    reason for reason in missing_reasons 
                    if not reason.startswith("cover_")
                ]
                # 只有当标题或内容缺失时才记录
                if important_missing:
                    reason_str = ",".join(missing_reasons)
                    self._record_no_content_domain(final_domain, final_url, reason_str)
            if result:
                result['domain'] = final_domain
                result['final_url'] = final_url  # 保存最终URL
                return result
            else:
                result['domain'] = final_domain
                result['final_url'] = final_url  
                result['missing_reasons'] = missing_reasons
                self.logger.debug(f"未提取到任何内容，域名: {final_domain}")
                return result
                
        except Exception as e:
            err_msg = str(e)
            if "Execution context was destroyed" in err_msg or "most likely because of a navigation" in err_msg:
                self.logger.debug(f"获取第三方新闻失败（页面已跳转，执行上下文失效）: {url}")
            else:
                self.logger.debug(f"获取第三方新闻失败: {e}, URL: {url}")
                import traceback
                self.logger.debug(traceback.format_exc())
            return None
        finally:
            await new_page.close()
    
    async def crawl_topic_page(self, topic_name: str, topic_url: str) -> List[Dict[str, Any]]:
        """爬取主题页面"""
        self.logger.info(f"开始爬取主题页面: {topic_name}")
        
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
            # 注入 XPath 评估器函数（只注入一次）
            await context.add_init_script(self._get_xpath_evaluator_script())
            page = await context.new_page()
            
            try:
                # 访问主题页面
                await page.goto(topic_url, wait_until="networkidle")
                await asyncio.sleep(self.request_delay)
                
                # 检查登录状态
                if not await self.check_login(page):
                    self.logger.error("未登录，请先运行 tools/login.py 登录")
                    raise Exception("未登录状态")
                
                # 滚动加载更多
                await self.scroll_and_load_more(page)
                
                # 提取新闻项
                articles = await self.extract_news_items(page)
                
                # 为每个文章添加主题信息
                for article in articles:
                    article["topic"] = topic_name
                
                # 并行获取第三方新闻内容（最多 5 个并发）
                third_party_concurrency = self.config.get("third_party_concurrency", 5)
                semaphore = asyncio.Semaphore(third_party_concurrency)
                task_items = []
                for article in articles:
                    for source in article.get("sources", []):
                        source_url = source.get("url")
                        if source_url:
                            task_items.append((article, source, source_url))
                
                async def fetch_third_party(article, source, source_url):
                    async with semaphore:
                        self.logger.info(f"正在获取第三方新闻内容: {source_url}")
                        info = await self._get_third_party_news(context, source_url)
                        return (article, source, source_url, info)
                
                results = await asyncio.gather(
                    *[fetch_third_party(a, s, u) for a, s, u in task_items],
                    return_exceptions=True
                )
                for r in results:
                    if isinstance(r, Exception):
                        self.logger.error(f"获取第三方新闻内容异常: {r}")
                    else:
                        _article, _source, _url, third_party_info = r
                        if third_party_info:
                            _source.update(third_party_info)
                            self.logger.info(f"✓ 成功获取第三方新闻内容，域名: {third_party_info.get('domain')}")
                        else:
                            self.logger.debug(f"未获取到第三方新闻内容: {_url}")
                
                self.logger.info(f"主题 {topic_name} 爬取完成，共 {len(articles)} 条新闻")
                return articles
            except Exception as e:
                self.logger.error(f"爬取主题页面失败 {topic_name}: {e}")
                return []
            finally:
                await browser.close()
    
    async def crawl_all_topics(self, topics: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """爬取所有主题"""
        all_articles = []
        
        for topic in topics:
            topic_name = topic.get("name", "")
            topic_url = topic.get("url", "")
            
            if not topic_url:
                self.logger.warning(f"主题 {topic_name} 没有 URL，跳过")
                continue
            
            articles = await self.crawl_topic_page(topic_name, topic_url)
            all_articles.extend(articles)
            
            # 延迟，避免请求过快
            await asyncio.sleep(self.request_delay)
        
        return all_articles


# 单独调试功能
if __name__ == "__main__":
    async def test_get_topic_links():
        """测试获取主题链接功能"""
        print("=== 测试获取主题链接功能 ===")
        
        # 加载配置
        config = load_config()
        selectors = load_selectors()
        logger = get_logger()
        
        # 创建爬取器
        crawler_config = config.get("crawler", {})
        crawler = GoogleNewsCrawler(crawler_config, selectors, logger)
        
        # 启动浏览器
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,  # 调试时显示浏览器
                args=get_browser_launch_args()
            )
            
            # 加载 session
            session_file = Path(crawler.session_file)
            storage_state = str(session_file) if session_file.exists() else None
            context_options = get_browser_context_options(
                storage_state=storage_state,
                proxy=crawler.proxy
            )
            
            context = await browser.new_context(**context_options)
            await context.add_init_script(get_anti_detection_script())
            page = await context.new_page()
            
            try:
                # 访问 Google News 主页
                print(f"正在访问: {crawler.google_news_url}")
                await page.goto(crawler.google_news_url, wait_until="networkidle")
                await asyncio.sleep(2)
                
                # 检查登录状态
                if not await crawler.check_login(page):
                    print("⚠️ 未登录，请先运行 tools/login.py 登录")
                    return
                
                # 获取主题链接
                print("\n开始获取主题链接...")
                topic_links = await crawler.get_topic_links(page)
                
                # 显示结果
                print(f"\n✓ 找到 {len(topic_links)} 个主题链接:")
                print("=" * 60)
                for i, link in enumerate(topic_links, 1):
                    print(f"{i:2d}. {link.get('name', '未知')}")
                    print(f"    URL: {link.get('url', '')}")
                print("=" * 60)
                
            except Exception as e:
                print(f"❌ 测试失败: {e}")
                import traceback
                traceback.print_exc()
            finally:
                input("\n按 Enter 关闭浏览器...")
                await browser.close()
    
    # 运行测试
    asyncio.run(test_get_topic_links())
