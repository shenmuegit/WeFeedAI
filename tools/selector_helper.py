"""可视化辅助工具，帮助选择页面元素并生成定位配置"""
import asyncio
import sys
import yaml
import json
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright, Page
from typing import Dict, Any, Optional
from src.utils.browser_config import get_browser_context_options, get_anti_detection_script, get_browser_launch_args


class SelectorHelper:
    """选择器辅助工具"""
    
    def __init__(self, session_file: str = "data/session_state.json"):
        self.session_file = session_file
        self.config = {}
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None
        # 存储已选元素的标识，用于重复检测
        self.selected_elements = {}  # {element_key: element_info}
        # 当前正在配置的第三方新闻域名
        self.current_third_party_domain = None
        # 是否正在等待第三方新闻配置（选择选项7后设置为True）
        self.waiting_for_third_party_news: bool = False
    
    async def setup_browser(self):
        """设置浏览器"""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                args=get_browser_launch_args()
            )
        except Exception as e:
            error_msg = str(e)
            if "Executable doesn't exist" in error_msg or "BrowserType.launch" in error_msg:
                print("\n" + "="*60)
                print("❌ 错误: Playwright 浏览器未安装")
                print("="*60)
                print("\n请运行以下命令安装浏览器:")
                print("  python -m playwright install chromium")
                print("\n或者安装所有浏览器:")
                print("  python -m playwright install")
                print("\n如果遇到网络问题，请:")
                print("  1. 检查网络连接")
                print("  2. 使用代理或 VPN")
                print("  3. 稍后重试")
                print("="*60)
                import sys
                sys.exit(1)
            else:
                raise
        
        # 设置真实的浏览器上下文配置
        storage_state = self.session_file if Path(self.session_file).exists() else None
        context_options = get_browser_context_options(
            storage_state=storage_state,
            proxy="http://127.0.0.1:1080"
        )
        
        self.context = await self.browser.new_context(**context_options)
        
        # 移除 webdriver 特征
        await self.context.add_init_script(get_anti_detection_script())
        
        self.page = await self.context.new_page()
        
        # 监听新标签页创建
        self.context.on("page", self._handle_new_page)
    
    async def inject_selection_script(self):
        """注入元素选择脚本"""
        script = r"""
        // 移除旧的事件监听器（如果存在）
        if (window.__playwright_click_handler) {
            document.removeEventListener('click', window.__playwright_click_handler, true);
            window.__playwright_click_handler = null;
        }
        
        // 移除旧的事件拦截器（如果存在）
        if (window.__playwright_event_interceptor) {
            const eventTypes = ['click', 'submit', 'mousedown', 'mouseup', 'touchstart', 'touchend', 'keydown', 'keyup'];
            eventTypes.forEach(function(eventType) {
                document.removeEventListener(eventType, window.__playwright_event_interceptor, true);
            });
            window.__playwright_event_interceptor = null;
        }
        
        window.selectedElement = null;
        window.highlightedElements = [];
        window.selectedElementInfo = null;
        
        function highlightElement(element) {
            element.style.outline = '3px solid red';
            element.style.backgroundColor = 'rgba(255, 0, 0, 0.2)';
        }
        
        function removeHighlight(element) {
            element.style.outline = '';
            element.style.backgroundColor = '';
        }
        
        function highlightAllByXPath(xpath) {
            // 使用 XPath 高亮所有匹配的元素
            const result = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
            for (let i = 0; i < result.snapshotLength; i++) {
                const el = result.snapshotItem(i);
                highlightElement(el);
                window.highlightedElements.push(el);
            }
        }
        
        function highlightAllByTagPath(tagPath) {
            // 使用标签路径高亮所有匹配的元素
            // 格式：html.body.div.section.article
            const parts = tagPath.split('.');
            let elements = [document];
            
            for (let i = 0; i < parts.length; i++) {
                const part = parts[i];
                const nextElements = [];
                
                // 处理带索引的标签，如 div[2]
                const match = part.match(/^(\w+)(?:\[(\d+)\])?$/);
                if (!match) continue;
                
                const tagName = match[1];
                const index = match[2] ? parseInt(match[2]) - 1 : null;
                
                for (const parent of elements) {
                    const children = Array.from(parent.getElementsByTagName(tagName));
                    if (index !== null) {
                        // 只选择指定索引的元素
                        if (children[index]) {
                            nextElements.push(children[index]);
                        }
                    } else {
                        // 选择所有匹配的元素
                        nextElements.push(...children);
                    }
                }
                
                elements = nextElements;
            }
            
            elements.forEach(el => {
                highlightElement(el);
                window.highlightedElements.push(el);
            });
        }
        
        function highlightAllByText(text) {
            // 通过文本内容高亮所有匹配的元素
            const walker = document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );
            let node;
            while (node = walker.nextNode()) {
                if (node.textContent.trim().includes(text)) {
                    const parent = node.parentElement;
                    if (parent) {
                        highlightElement(parent);
                        window.highlightedElements.push(parent);
                    }
                }
            }
        }
        
        function removeAllHighlights() {
            window.highlightedElements.forEach(removeHighlight);
            window.highlightedElements = [];
        }
        
        function scrollToBottomUntilNoNewContent() {
            // 滚动到底部，直到没有新的网络请求为止（返回Promise）
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
        
        function getAllSiblings(element, useParentChildren = true) {
            // 获取元素的所有兄弟元素
            // useParentChildren: true - 获取父元素的所有子元素；false - 只获取相同标签的兄弟元素
            if (!element || !element.parentNode) return [];
            const parent = element.parentNode;
            
            if (useParentChildren) {
                // 获取父元素的所有子元素（不限制标签名）
                return Array.from(parent.children);
            } else {
                // 只获取相同标签名的兄弟元素
                const tagName = element.tagName;
                const siblings = Array.from(parent.children).filter(
                    child => child.tagName === tagName && child !== element
                );
                return [element, ...siblings]; // 包含自身
            }
        }
        
        function highlightAllSiblings(element, useParentChildren = true) {
            // 高亮元素的所有兄弟元素
            const siblings = getAllSiblings(element, useParentChildren);
            removeAllHighlights();
            siblings.forEach(el => {
                highlightElement(el);
                window.highlightedElements.push(el);
            });
            return siblings.length;
        }
        
        function getElementHTML(element) {
            // 获取元素的HTML内容（包括自身）
            if (!element) return '';
            return element.outerHTML || element.innerHTML || '';
        }
        
        function getPreviousSibling(element) {
            // 获取上一个兄弟节点（跳过文本节点）
            if (!element || !element.parentNode) return null;
            let prev = element.previousElementSibling;
            while (prev && prev.nodeType !== 1) {
                prev = prev.previousSibling;
            }
            return prev;
        }
        
        function getNextSibling(element) {
            // 获取下一个兄弟节点（跳过文本节点）
            if (!element || !element.parentNode) return null;
            let next = element.nextElementSibling;
            while (next && next.nodeType !== 1) {
                next = next.nextSibling;
            }
            return next;
        }
        
        function getParentElement(element) {
            // 获取父元素（只返回元素节点）
            if (!element || !element.parentNode) return null;
            // 优先使用 parentElement（只返回元素节点）
            if (element.parentElement) {
                return element.parentElement;
            }
            // 如果 parentElement 不存在，检查 parentNode 是否是元素节点
            const parent = element.parentNode;
            if (parent && parent.nodeType === 1) {
                return parent;
            }
            return null;
        }
        
        function getFirstChildElement(element) {
            // 获取第一个子元素
            if (!element) return null;
            let child = element.firstElementChild;
            return child || null;
        }
        
        function saveElementInfo(element) {
            // 立即保存元素信息到 sessionStorage，防止页面跳转丢失
            try {
                const info = {
                    tag: element.tagName.toLowerCase(),
                    text: element.textContent?.trim().substring(0, 50) || '',
                    class: element.className || '',
                    href: element.href || element.getAttribute('href') || '',
                    xpath: getXPath(element),
                    tagpath: getTagPath(element),
                    html: getElementHTML(element)
                };
                
                // 保存到 sessionStorage
                sessionStorage.setItem('__playwright_selected_element', JSON.stringify(info));
                window.selectedElementInfo = info;
            } catch(e) {
                console.warn('Failed to save element info:', e);
            }
        }
        
        function navigateToSibling(element, direction) {
            // direction: 'prev' 或 'next'
            if (!element) {
                console.warn('navigateToSibling: element is null');
                return false;
            }
            const sibling = direction === 'prev' ? getPreviousSibling(element) : getNextSibling(element);
            if (sibling) {
                window.selectedElement = sibling;
                saveElementInfo(sibling);
                removeAllHighlights();
                highlightElement(sibling);
                window.highlightedElements.push(sibling);
                return true;
            } else {
                console.warn('navigateToSibling: no sibling element found, direction:', direction);
            }
            return false;
        }
        
        function navigateToParent(element) {
            // 导航到父元素
            if (!element) {
                console.warn('navigateToParent: element is null');
                return false;
            }
            const parent = getParentElement(element);
            if (parent) {
                // getParentElement 已经确保返回的是元素节点
                window.selectedElement = parent;
                saveElementInfo(parent);
                removeAllHighlights();
                highlightElement(parent);
                window.highlightedElements.push(parent);
                return true;
            } else {
                console.warn('navigateToParent: no parent element found');
            }
            return false;
        }
        
        function navigateToChild(element) {
            // 导航到第一个子元素
            if (!element) {
                console.warn('navigateToChild: element is null');
                return false;
            }
            const child = getFirstChildElement(element);
            if (child) {
                window.selectedElement = child;
                saveElementInfo(child);
                removeAllHighlights();
                highlightElement(child);
                window.highlightedElements.push(child);
                return true;
            } else {
                console.warn('navigateToChild: no child element found');
            }
            return false;
        }
        
        // 暴露导航函数到全局
        window.navigateToPreviousSibling = function() {
            if (window.selectedElement) {
                return navigateToSibling(window.selectedElement, 'prev');
            }
            return false;
        };
        
        window.navigateToNextSibling = function() {
            if (window.selectedElement) {
                return navigateToSibling(window.selectedElement, 'next');
            }
            return false;
        };
        
        function restoreSelectedElement() {
            // 尝试从 sessionStorage 恢复 selectedElement
            if (window.selectedElement && document.contains(window.selectedElement)) {
                return window.selectedElement;
            }
            
            // 如果 selectedElement 不存在或无效，尝试从保存的信息恢复
            if (window.selectedElementInfo) {
                const info = window.selectedElementInfo;
                let element = null;
                
                // 优先使用 xpath 恢复
                if (info.xpath) {
                    try {
                        const result = document.evaluate(info.xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                        element = result.singleNodeValue;
                    } catch(e) {
                        console.warn('Failed to restore element from xpath:', e);
                    }
                }
                
                // 如果 xpath 失败，尝试使用 tagpath
                if (!element && info.tagpath) {
                    try {
                        const parts = info.tagpath.split('.');
                        let elements = [document];
                        
                        for (let i = 0; i < parts.length; i++) {
                            const part = parts[i];
                            const match = part.match(/^(\w+)(?:\[(\d+)\])?$/);
                            if (!match) continue;
                            
                            const tagName = match[1];
                            const index = match[2] ? parseInt(match[2]) - 1 : null;
                            const nextElements = [];
                            
                            for (const parent of elements) {
                                const children = Array.from(parent.getElementsByTagName(tagName));
                                if (index !== null) {
                                    if (children[index]) {
                                        nextElements.push(children[index]);
                                    }
                                } else {
                                    nextElements.push(...children);
                                }
                            }
                            
                            elements = nextElements;
                        }
                        
                        if (elements.length > 0) {
                            element = elements[0];
                        }
                    } catch(e) {
                        console.warn('Failed to restore element from tagpath:', e);
                    }
                }
                
                if (element && document.contains(element)) {
                    window.selectedElement = element;
                    return element;
                }
            }
            
            return null;
        }
        
        window.navigateToParent = function() {
            let element = restoreSelectedElement();
            if (!element) {
                console.warn('navigateToParent: cannot restore selectedElement');
                return false;
            }
            return navigateToParent(element);
        };
        
        window.navigateToChild = function() {
            let element = restoreSelectedElement();
            if (!element) {
                console.warn('navigateToChild: cannot restore selectedElement');
                return false;
            }
            return navigateToChild(element);
        };
        
        window.navigateToPreviousSiblingElement = function() {
            let element = restoreSelectedElement();
            if (!element) {
                console.warn('navigateToPreviousSiblingElement: cannot restore selectedElement');
                return false;
            }
            return navigateToSibling(element, 'prev');
        };
        
        window.navigateToNextSiblingElement = function() {
            let element = restoreSelectedElement();
            if (!element) {
                console.warn('navigateToNextSiblingElement: cannot restore selectedElement');
                return false;
            }
            return navigateToSibling(element, 'next');
        };
        
        // 暴露滚动和兄弟元素函数到全局
        window.scrollToBottomUntilNoNewContent = scrollToBottomUntilNoNewContent;
        window.getAllSiblings = getAllSiblings;
        window.highlightAllSiblings = highlightAllSiblings;
        
        function getXPath(element) {
            // 不使用 id，直接从标签结构生成 XPath
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
        
        function getTagPath(element) {
            // 生成标签路径，格式：html.body.div.section.article
            // 从根节点开始，只使用标签名
            const path = [];
            let current = element;
            
            while (current && current !== document && current !== document.documentElement) {
                if (current.nodeType === 1) { // Element node
                    const tagName = current.tagName.toLowerCase();
                    // 如果有多个相同标签的兄弟节点，添加索引
                    const siblings = current.parentNode ? Array.from(current.parentNode.children) : [];
                    const sameTagSiblings = siblings.filter(s => s.tagName.toLowerCase() === tagName);
                    if (sameTagSiblings.length > 1) {
                        const index = sameTagSiblings.indexOf(current) + 1;
                        path.unshift(`${tagName}[${index}]`);
                    } else {
                        path.unshift(tagName);
                    }
                }
                current = current.parentNode;
            }
            
            // 添加 html 根节点
            if (document.documentElement) {
                path.unshift('html');
            }
            
            return path.join('.');
        }
        
        function restoreElementInfo() {
            // 页面加载后恢复元素信息
            try {
                const saved = sessionStorage.getItem('__playwright_selected_element');
                if (saved) {
                    window.selectedElementInfo = JSON.parse(saved);
                    return true;
                }
            } catch(e) {
                console.warn('Failed to restore element info:', e);
            }
            return false;
        }
        
        // 页面加载时尝试恢复元素信息
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', restoreElementInfo);
        } else {
            restoreElementInfo();
        }
        
        // 检查是否是 consent 页面，如果是则不注入事件拦截器
        const isConsentPage = window.location.hostname === 'consent.google.com';
        
        // 如果不是 consent 页面，才注入事件拦截器和点击处理函数
        if (!isConsentPage) {
        // 拦截所有事件的处理函数（阻止按钮的默认行为，但允许元素选择）
        window.__playwright_event_interceptor = function(e) {
            const target = e.target;
            const tagName = target.tagName.toLowerCase();
            const linkElement = target.tagName === 'A' ? target : target.closest('a');
            
            // 如果正在选择主题链接，拦截链接的点击事件
            if (linkElement && window.__selecting_topic_link && e.type === 'click') {
                console.log('[DEBUG] 事件拦截器 - 检测到链接点击，正在选择主题链接模式，阻止默认行为');
                e.preventDefault();
                e.__topic_link_prevented = true;
                // 不阻止事件传播，让点击处理函数能够执行
            }
            
            // 拦截按钮的所有事件（阻止默认行为，但允许选择）
            // 注意：这个拦截器在捕获阶段运行，会在点击处理函数之前执行
            // 但我们需要让点击处理函数先执行来选择元素，所以这里只阻止默认行为
            if (tagName === 'button' || target.closest('button')) {
                // 只阻止默认行为，不阻止事件传播，让点击处理函数能够处理
                e.preventDefault();
                // 对于非 click 事件，完全阻止
                if (e.type !== 'click') {
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    return false;
                }
            }
            
            // 拦截表单提交
            if (tagName === 'form' || target.closest('form')) {
                if (e.type === 'submit') {
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    return false;
                }
            }
            
            // 拦截输入框的某些事件（保留输入功能，但阻止提交）
            if (tagName === 'input' && target.type === 'submit') {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                return false;
            }
        };
        
        // 拦截所有常见事件类型
        const eventTypes = ['click', 'submit', 'mousedown', 'mouseup', 'touchstart', 'touchend', 'keydown', 'keyup'];
        eventTypes.forEach(function(eventType) {
            document.addEventListener(eventType, window.__playwright_event_interceptor, true);
        });
        
        // 创建点击事件处理函数（用于元素选择）
        window.__playwright_click_handler = function(e) {
            // 检查点击的元素是否是链接或其子元素
            const clickedElement = e.target;
            const linkElement = clickedElement.tagName === 'A' ? clickedElement : clickedElement.closest('a');
            const isLink = !!linkElement;
            
            // 检查是否是按钮（包括按钮本身或其子元素）
            const buttonElement = clickedElement.tagName === 'BUTTON' ? clickedElement : clickedElement.closest('button');
            const isButton = !!buttonElement;
            
            // 先保存元素信息
            // 如果是按钮，保存按钮元素；如果是链接，保存链接元素；否则保存实际点击的元素
            let elementToSave = clickedElement;
            if (isButton) {
                elementToSave = buttonElement;
            } else if (isLink) {
                elementToSave = linkElement;
            }
            saveElementInfo(elementToSave);
            
            // 设置选中元素
            const elementToSelect = isButton ? buttonElement : (isLink ? linkElement : clickedElement);
            window.selectedElement = elementToSelect;
            removeAllHighlights();
            highlightElement(elementToSelect);
            
            // 如果是按钮，阻止事件传播（默认行为已在拦截器中阻止）
            if (isButton) {
                e.stopPropagation();
                e.stopImmediatePropagation();
                return false;
            }
            
            // 如果是链接，检查是否在选择主题链接模式
            if (isLink) {
                console.log('[DEBUG] 点击处理函数 - 检测到链接, __selecting_topic_link:', window.__selecting_topic_link, '__topic_link_prevented:', e.__topic_link_prevented);
                // 如果正在选择主题链接，阻止跳转
                if (window.__selecting_topic_link || e.__topic_link_prevented) {
                    console.log('[DEBUG] 点击处理函数 - 阻止链接跳转');
                    e.preventDefault();
                    e.stopPropagation();
                    return false;
                }
                console.log('[DEBUG] 点击处理函数 - 允许链接跳转');
                // 否则不阻止链接跳转，让用户正常浏览
                // 信息已保存到 sessionStorage，可以在新页面恢复
                return; // 不阻止事件，让链接正常跳转
            } else {
                // 非链接元素，阻止默认行为
                e.preventDefault();
                e.stopPropagation();
            }
        };
        
        // 添加点击事件监听器（使用捕获阶段，但链接不阻止）
        document.addEventListener('click', window.__playwright_click_handler, true);
        }
        """
        await self.page.evaluate(script)
        
        # 监听页面跳转，在新页面加载后恢复脚本
        self.page.on("framenavigated", self._handle_page_navigation)
        
        # 监听页面请求，在跳转前尝试保存元素信息
        self.page.on("request", self._handle_page_request)
    
    async def _handle_new_page(self, page):
        """处理新标签页创建"""
        # 等待页面加载
        try:
            await page.wait_for_load_state("domcontentloaded")
        except:
            pass
        
        # 检查是否正在等待第三方新闻配置（选择选项7后）
        if self.waiting_for_third_party_news:
            original_page = None
            try:
                # 获取新标签页的初始URL
                initial_url = page.url
                is_google_news_link = "news.google.com/read" in initial_url
                
                # 如果是 Google News 内部链接，等待重定向
                if is_google_news_link:
                    print(f"检测到 Google News 内部链接，等待重定向...")
                    print(f"初始链接: {initial_url}")
                    
                    # 等待重定向完成（URL 不再包含 news.google.com/read）
                    try:
                        await page.wait_for_url(
                            lambda url: "news.google.com/read" not in url,
                            timeout=60000  # 60秒超时
                        )
                        final_url = page.url
                        print(f"✓ 重定向完成，最终URL: {final_url}")
                    except Exception as e:
                        print(f"⚠️ 等待重定向超时或失败: {e}")
                        print(f"当前URL: {page.url}")
                        # 即使超时，也继续使用当前页面
                        final_url = page.url
                else:
                    # 不是 Google News 链接，直接使用当前URL
                    final_url = page.url
                
                # 从最终URL提取域名
                domain = self.extract_domain_from_url(final_url)
                if not domain:
                    print("⚠️ 无法从链接中提取域名，请检查链接格式")
                    self.waiting_for_third_party_news = False
                    return
                
                print(f"\n提取的域名: {domain}")
                
                # 检查域名配置并确认是否继续
                should_continue = await self._check_and_confirm_domain_config(domain)
                if not should_continue:
                    self.waiting_for_third_party_news = False
                    return
                
                # 设置当前配置的域名
                self.current_third_party_domain = domain
                
                # 保存原页面并切换到新标签页
                original_page = self.page
                self.page = page
                
                # 在新标签页注入脚本
                await self.inject_selection_script()
                print(f"✓ 已在新标签页中注入选择脚本")
                
                # 显示元素配置菜单
                await self._show_third_party_element_menu(domain)
                
            except Exception as e:
                print(f"⚠️ 处理第三方新闻配置时出错: {e}")
                import traceback
                traceback.print_exc()
            finally:
                # 清理工作
                try:
                    # 如果使用了新标签页，关闭它并切换回原页面
                    if original_page is not None:
                        if not page.is_closed():
                            await page.close()
                        self.page = original_page
                        print(f"✓ 已关闭新标签页，切换回原页面")
                except Exception as e:
                    print(f"⚠️ 关闭新标签页时出错: {e}")
                
                # 重置状态
                self.waiting_for_third_party_news = False
                self.current_third_party_domain = None
        
        # 在新标签页中注入脚本（无论是否处理第三方新闻配置，都要注入脚本）
        try:
            if not page.is_closed():
                # 在新标签页中注入选择脚本（简化版，只包含基本功能）
                script = r"""
                // 移除旧的事件监听器（如果存在）
                if (window.__playwright_click_handler) {
                    document.removeEventListener('click', window.__playwright_click_handler, true);
                    window.__playwright_click_handler = null;
                }
                
                // 移除旧的事件拦截器（如果存在）
                if (window.__playwright_event_interceptor) {
                    const eventTypes = ['click', 'submit', 'mousedown', 'mouseup', 'touchstart', 'touchend', 'keydown', 'keyup'];
                    eventTypes.forEach(function(eventType) {
                        document.removeEventListener(eventType, window.__playwright_event_interceptor, true);
                    });
                    window.__playwright_event_interceptor = null;
                }
                
                window.selectedElement = null;
                window.highlightedElements = [];
                window.selectedElementInfo = null;
                
                function highlightElement(element) {
                    element.style.outline = '3px solid red';
                    element.style.backgroundColor = 'rgba(255, 0, 0, 0.2)';
                }
                
                function removeHighlight(element) {
                    element.style.outline = '';
                    element.style.backgroundColor = '';
                }
                
                function removeAllHighlights() {
                    if (window.highlightedElements) {
                        window.highlightedElements.forEach(removeHighlight);
                        window.highlightedElements = [];
                    }
                }
                
                // 拦截所有事件的处理函数（阻止按钮的默认行为，但允许元素选择）
                window.__playwright_event_interceptor = function(e) {
                    const target = e.target;
                    const tagName = target.tagName.toLowerCase();
                    
                    // 拦截按钮的所有事件（阻止默认行为，但允许选择）
                    if (tagName === 'button' || target.closest('button')) {
                        // 只阻止默认行为，不阻止事件传播，让点击处理函数能够处理
                        e.preventDefault();
                        // 对于非 click 事件，完全阻止
                        if (e.type !== 'click') {
                            e.stopPropagation();
                            e.stopImmediatePropagation();
                            return false;
                        }
                    }
                    
                    // 拦截表单提交
                    if (tagName === 'form' || target.closest('form')) {
                        if (e.type === 'submit') {
                            e.preventDefault();
                            e.stopPropagation();
                            e.stopImmediatePropagation();
                            return false;
                        }
                    }
                    
                    // 拦截输入框的某些事件（保留输入功能，但阻止提交）
                    if (tagName === 'input' && target.type === 'submit') {
                        e.preventDefault();
                        e.stopPropagation();
                        e.stopImmediatePropagation();
                        return false;
                    }
                };
                
                // 拦截所有常见事件类型
                const eventTypes = ['click', 'submit', 'mousedown', 'mouseup', 'touchstart', 'touchend', 'keydown', 'keyup'];
                eventTypes.forEach(function(eventType) {
                    document.addEventListener(eventType, window.__playwright_event_interceptor, true);
                });
                
                // 创建点击事件处理函数（用于元素选择）
                window.__playwright_click_handler = function(e) {
                    const clickedElement = e.target;
                    const linkElement = clickedElement.tagName === 'A' ? clickedElement : clickedElement.closest('a');
                    const isLink = !!linkElement;
                    
                    // 检查是否是按钮（包括按钮本身或其子元素）
                    const buttonElement = clickedElement.tagName === 'BUTTON' ? clickedElement : clickedElement.closest('button');
                    const isButton = !!buttonElement;
                    
                    // 先保存元素信息
                    // 如果是按钮，保存按钮元素；如果是链接，保存链接元素；否则保存实际点击的元素
                    let elementToSave = clickedElement;
                    if (isButton) {
                        elementToSave = buttonElement;
                    } else if (isLink) {
                        elementToSave = linkElement;
                    }
                    
                    // 设置选中元素
                    const elementToSelect = isButton ? buttonElement : (isLink ? linkElement : clickedElement);
                    window.selectedElement = elementToSelect;
                    removeAllHighlights();
                    highlightElement(elementToSelect);
                    
                    // 如果是按钮，阻止事件传播（默认行为已在拦截器中阻止）
                    if (isButton) {
                        e.stopPropagation();
                        e.stopImmediatePropagation();
                        return false;
                    }
                    
                    if (isLink) {
                        return;
                    } else {
                        e.preventDefault();
                        e.stopPropagation();
                    }
                };
                
                document.addEventListener('click', window.__playwright_click_handler, true);
                """
                await page.evaluate(script)
                print(f"✓ 已在新标签页中注入选择脚本")
        except Exception as e:
            # 页面可能已关闭或导航中，忽略错误
            pass
    
    async def _handle_page_navigation(self, frame):
        """处理页面导航，在新页面加载后恢复元素信息"""
        if frame == self.page.main_frame:
            # 等待页面加载
            try:
                await self.page.wait_for_load_state("domcontentloaded")
            except:
                pass
            # 新页面加载后，重新注入脚本
            try:
                # 检查页面是否已关闭
                if not self.page.is_closed():
                    await self.inject_selection_script()
            except Exception as e:
                # 页面可能已关闭或导航中，忽略错误
                pass
    
    async def _handle_page_request(self, request):
        """处理页面请求，在跳转前保存元素信息"""
        # 如果是导航请求，尝试保存当前选中的元素信息
        if request.resource_type == "document":
            try:
                # 立即获取并保存元素信息
                await self.page.evaluate("""
                    () => {
                        if (window.selectedElement) {
                            const element = window.selectedElement;
                            const info = {
                                tag: element.tagName.toLowerCase(),
                                text: element.textContent?.trim().substring(0, 50) || '',
                                class: element.className || '',
                                href: element.href || element.getAttribute('href') || ''
                            };
                            sessionStorage.setItem('__playwright_selected_element', JSON.stringify(info));
                        }
                    }
                """)
            except:
                pass
    
    async def handle_google_consent(self, page: Optional[Page] = None) -> bool:
        """处理 Google Cookie 同意页面
        
        Args:
            page: 要处理的页面，如果为 None 则使用 self.page
            
        Returns:
            bool: True 表示已处理或无需处理，False 表示处理失败
        """
        try:
            target_page = page if page is not None else self.page
            if target_page.is_closed():
                return False
            
            current_url = target_page.url
            parsed = urlparse(current_url)
            netloc = parsed.netloc
            
            # 检查域名是否以 .google.com 结尾
            if not netloc.endswith('.google.com'):
                return True
            
            # 等待页面加载完成
            try:
                await target_page.wait_for_load_state("domcontentloaded", timeout=10000)
            except:
                pass
            
            # 定义按钮 xpath（指向 button 元素，不是 span）
            button_xpath = "/html/body/c-wiz/div/div/div/div[2]/div[1]/div[3]/div[1]/div[1]/form[1]/div/div/button"
            
            # 检查按钮是否存在
            button_count = await target_page.locator(f"xpath={button_xpath}").count()
            
            if button_count > 0:
                # 点击按钮
                await target_page.locator(f"xpath={button_xpath}").click()
                print("✓ 已自动点击 Cookie 同意按钮")
                
                # 等待页面处理（等待按钮消失或页面跳转，最多 5 秒）
                try:
                    await target_page.wait_for_load_state("domcontentloaded", timeout=5000)
                except:
                    pass
                
                return True
            else:
                # 按钮不存在，无需处理
                return True
        except Exception as e:
            # 处理失败，但不影响主流程
            return False
    
    def _get_element_key(self, info: Dict[str, Any]) -> str:
        """生成元素的唯一标识键"""
        # 优先使用 tagpath，其次 xpath，最后 text
        key = info.get('tagpath', '') or info.get('xpath', '') or info.get('text', '')
        return key
    
    def _check_duplicate(self, info: Dict[str, Any], element_name: str) -> bool:
        """检测元素是否重复选择"""
        key = self._get_element_key(info)
        if not key:
            return False
        
        if key in self.selected_elements:
            existing = self.selected_elements[key]
            print(f"\n⚠️ 检测到重复选择！")
            print(f"  当前元素: {element_name}")
            print(f"  已选元素: {existing.get('name', '未知')}")
            print(f"  标识: {key[:100]}...")
            return True
        return False
    
    def _register_element(self, info: Dict[str, Any], element_name: str):
        """注册已选元素"""
        key = self._get_element_key(info)
        if key:
            self.selected_elements[key] = {
                'name': element_name,
                'info': info.copy()
            }
    
    def clear_selected_elements(self):
        """清空所有已选元素的标识"""
        self.selected_elements.clear()
        print("\n✓ 已清空所有已选元素的标识")
    
    def clear_element(self, info: Dict[str, Any], element_name: str = "") -> bool:
        """清除指定的已选元素"""
        key = self._get_element_key(info)
        if key and key in self.selected_elements:
            removed_name = self.selected_elements[key].get('name', element_name)
            del self.selected_elements[key]
            print(f"\n✓ 已清除元素: {removed_name}")
            return True
        elif key:
            print(f"\n⚠️ 未找到要清除的元素")
            return False
        else:
            print(f"\n⚠️ 无法生成元素标识，无法清除")
            return False
    
    def show_selected_elements(self):
        """显示所有已选元素"""
        if not self.selected_elements:
            print("\n当前没有已选元素")
            return
        
        print("\n已选元素列表:")
        for idx, (key, data) in enumerate(self.selected_elements.items(), 1):
            print(f"  {idx}. {data['name']}")
            print(f"     标识: {key[:80]}...")
    
    async def safe_evaluate(self, script: str, default=None):
        """安全地执行 page.evaluate，处理页面关闭或导航的情况"""
        try:
            if self.page.is_closed():
                return default
            return await self.page.evaluate(script)
        except Exception as e:
            # 页面可能已关闭或导航中，返回默认值
            return default
    
    def show_location_info(self, info: Dict[str, Any]):
        """显示定位信息供用户选择"""
        print(f"\n{'='*60}")
        print(f"可用的定位信息:")
        print(f"{'='*60}")
        tagpath = info.get('tagpath', '')
        xpath = info.get('xpath', '')
        text = info.get('text', '')
        
        options = []
        if tagpath:
            options.append(('tagpath', tagpath))
            print(f"\n1. TagPath (标签路径):")
            print(f"   {tagpath[:200]}{'...' if len(tagpath) > 200 else ''}")
        if xpath:
            options.append(('xpath', xpath))
            print(f"\n2. XPath:")
            print(f"   {xpath[:200]}{'...' if len(xpath) > 200 else ''}")
        if text:
            options.append(('text', text))
            print(f"\n3. Text (文本内容):")
            print(f"   {text[:200]}{'...' if len(text) > 200 else ''}")
        print(f"{'='*60}")
        return options
    
    async def get_element_html(self) -> str:
        """获取选中元素的HTML内容"""
        html = await self.safe_evaluate("""
        () => {
            if (window.selectedElement && window.selectedElement.nodeType === 1) {
                return window.selectedElement.outerHTML || window.selectedElement.innerHTML || '';
            }
            return '';
        }
        """, default='')
        return html
    
    async def navigate_to_sibling(self, direction: str) -> bool:
        """导航到上一个或下一个兄弟节点"""
        result = await self.safe_evaluate(f"""
        () => {{
            if (window.navigateTo{'Previous' if direction == 'prev' else 'Next'}Sibling) {{
                return window.navigateTo{'Previous' if direction == 'prev' else 'Next'}Sibling();
            }}
            return false;
        }}
        """, default=False)
        return result
    
    async def navigate_to_parent(self) -> bool:
        """导航到父元素"""
        result = await self.safe_evaluate("""
        () => {
            if (window.navigateToParent) {
                return window.navigateToParent();
            }
            return false;
        }
        """, default=False)
        return result
    
    async def navigate_to_child(self) -> bool:
        """导航到第一个子元素"""
        result = await self.safe_evaluate("""
        () => {
            if (window.navigateToChild) {
                return window.navigateToChild();
            }
            return false;
        }
        """, default=False)
        return result
    
    async def navigate_to_previous_sibling_element(self) -> bool:
        """导航到上一个兄弟元素"""
        result = await self.safe_evaluate("""
        () => {
            if (window.navigateToPreviousSiblingElement) {
                return window.navigateToPreviousSiblingElement();
            }
            return false;
        }
        """, default=False)
        return result
    
    async def navigate_to_next_sibling_element(self) -> bool:
        """导航到下一个兄弟元素"""
        result = await self.safe_evaluate("""
        () => {
            if (window.navigateToNextSiblingElement) {
                return window.navigateToNextSiblingElement();
            }
            return false;
        }
        """, default=False)
        return result
    
    def print_element_html(self, info: Dict[str, Any]):
        """打印元素HTML内容"""
        html = info.get('html', '')
        if html:
            print(f"\n{'='*60}")
            print(f"所选元素的HTML内容:")
            print(f"{'='*60}")
            print(html)
            print(f"{'='*60}")
    
    async def wait_for_element_selection(self, element_name: str, wait_time: float = 0.5, re_inject_script: bool = False) -> Optional[Dict[str, Any]]:
        """等待用户选择元素并返回元素信息（统一的处理流程）"""
        while True:
            print("\n请选择操作:")
            print("  1. 确认")
            print("  2. 清空")
            choice = input("\n请输入选项 (1-2): ").strip()
            
            if choice == '1':
                # 等待页面稳定
                await asyncio.sleep(wait_time)
                
                # 如果需要重新注入脚本（如页面跳转）
                if re_inject_script:
                    try:
                        # 保存当前的选择主题链接标志
                        selecting_flag = await self.page.evaluate("() => window.__selecting_topic_link || false")
                        print(f"[DEBUG] 重新注入脚本前 __selecting_topic_link: {selecting_flag}")
                        await self.inject_selection_script()
                        # 恢复标志（如果之前设置了）
                        if selecting_flag:
                            await self.page.evaluate("() => { window.__selecting_topic_link = true; }")
                            print(f"[DEBUG] 重新注入脚本后恢复 __selecting_topic_link 标志")
                    except Exception as e:
                        print(f"[DEBUG] 重新注入脚本时出错: {e}")
                        pass
                
                # 获取元素信息
                info = await self.get_element_info()
                if not info:
                    print("\n⚠️ 未检测到选中的元素")
                    print("请先在浏览器中点击要选择的元素")
                    continue
                
                # 打印元素HTML
                self.print_element_html(info)
                
                return info
            elif choice == '2':
                # 清空：清空所有高亮元素和选中状态
                try:
                    # 直接调用，不使用 safe_evaluate，确保清空操作执行
                    if not self.page.is_closed():
                        await self.page.evaluate("""
                            () => {
                                if (typeof removeAllHighlights === 'function') {
                                    removeAllHighlights();
                                }
                                if (window.highlightedElements) {
                                    window.highlightedElements.forEach(function(el) {
                                        if (el && el.style) {
                                            el.style.outline = '';
                                            el.style.backgroundColor = '';
                                        }
                                    });
                                    window.highlightedElements = [];
                                }
                                window.selectedElement = null;
                                window.selectedElementInfo = null;
                            }
                        """)
                    print("\n✓ 已清空所有高亮元素")
                except Exception as e:
                    print(f"\n⚠️ 清空高亮元素时出错: {e}")
                return None
            else:
                print("无效选项，请重新选择")
    
    async def confirm_element_selection(self, element_name: str, html_already_printed: bool = False) -> Optional[Dict[str, Any]]:
        """统一的元素确认流程"""
        first_loop = True
        while True:
            # 获取元素信息
            info = await self.get_element_info()
            if not info:
                if first_loop:
                    print("\n⚠️ 未检测到选中的元素")
                    print("请先在浏览器中点击要选择的元素，然后按 Enter 继续...")
                    input()
                    # 重新尝试获取元素信息
                    await asyncio.sleep(0.3)
                    info = await self.get_element_info()
                    if not info:
                        print("\n仍然未检测到元素，是否重试？(y/n): ", end='')
                        retry = input().strip().lower()
                        if retry != 'y':
                            return None
                        continue
                    # 重新获取到元素，打印HTML
                    html_already_printed = False
                else:
                    print("\n⚠️ 未检测到选中的元素")
                    return None
            
            # 打印元素HTML（如果还没有打印过，或者用户导航到了新节点）
            if not html_already_printed or not first_loop:
                self.print_element_html(info)
                html_already_printed = True
            
            # 显示选项菜单
            print(f"\n请选择操作:")
            print(f"  1. 确认")
            print(f"  2. 清除")
            print(f"  3. 父元素")
            print(f"  4. 子元素")
            print(f"  5. 上一个元素（上一个兄弟节点）")
            print(f"  6. 下一个元素（下一个兄弟节点）")
            choice = input(f"\n请输入选项 (1-6): ").strip()
            
            if choice == '1':
                # 确认：再次显示HTML和href属性（新闻容器除外）
                self.print_element_html(info)
                
                # 检查是否是第三方新闻元素（标题/内容/封面/作者）
                is_third_party_element = '_' in element_name and any(
                    element_type in element_name for element_type in ['标题', '内容', '封面', '作者']
                )
                
                if is_third_party_element:
                    # 检查是否是封面元素
                    is_cover = '封面' in element_name or 'cover' in element_name.lower()
                    
                    if is_cover:
                        # 封面元素：查找source标签的srcset属性或img标签的src属性
                        cover_info = await self.safe_evaluate("""
                            () => {
                                if (!window.selectedElement) return null;
                                
                                const element = window.selectedElement;
                                let srcset = '';
                                let src = '';
                                
                                // 如果当前元素是source标签，获取srcset
                                if (element.tagName.toLowerCase() === 'source') {
                                    srcset = element.getAttribute('srcset') || '';
                                }
                                // 如果当前元素是img标签，获取src
                                else if (element.tagName.toLowerCase() === 'img') {
                                    src = element.getAttribute('src') || element.src || '';
                                }
                                // 否则，查找子元素中的source或img
                                else {
                                    const source = element.querySelector('source');
                                    if (source) {
                                        srcset = source.getAttribute('srcset') || '';
                                    }
                                    const img = element.querySelector('img');
                                    if (img) {
                                        src = img.getAttribute('src') || img.src || '';
                                    }
                                }
                                
                                return {
                                    srcset: srcset,
                                    src: src,
                                    found: srcset || src
                                };
                            }
                        """, default=None)
                        
                        if cover_info and cover_info.get('found'):
                            if cover_info.get('srcset'):
                                print(f"\n检测到的封面图片 (srcset):")
                                print(f"{'='*60}")
                                print(cover_info['srcset'][:500])
                                if len(cover_info['srcset']) > 500:
                                    print("...")
                                print(f"{'='*60}")
                            if cover_info.get('src'):
                                print(f"\n检测到的封面图片 (src):")
                                print(f"{'='*60}")
                                print(cover_info['src'][:500])
                                if len(cover_info['src']) > 500:
                                    print("...")
                                print(f"{'='*60}")
                        else:
                            print(f"\n⚠️ 未找到封面图片（source的srcset或img的src属性）")
                    else:
                        # 其他第三方新闻元素：显示文本内容（包括递归子元素的所有文本）
                        # 始终从页面元素获取完整文本，不使用 info 中截断的文本
                        # 先恢复元素
                        await self.safe_evaluate("""
                        () => {
                            // 尝试恢复 selectedElement
                            if (!window.selectedElement || !document.contains(window.selectedElement)) {
                                if (window.selectedElementInfo && window.selectedElementInfo.xpath) {
                                    try {
                                        const result = document.evaluate(window.selectedElementInfo.xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                                        const element = result.singleNodeValue;
                                        if (element) {
                                            window.selectedElement = element;
                                        }
                                    } catch(e) {
                                        console.warn('Failed to restore element from xpath:', e);
                                    }
                                }
                            }
                        }
                        """, default=None)
                        
                        # 从页面元素获取完整文本内容
                        text_content = await self.safe_evaluate("""
                            () => {
                                if (window.selectedElement && document.contains(window.selectedElement)) {
                                    const text = window.selectedElement.textContent || window.selectedElement.innerText || '';
                                    return text.trim();
                                }
                                return '';
                            }
                        """, default='')
                        
                        if text_content:
                            # 显示完整文本内容（不截断）
                            display_text = text_content.strip()
                            print(f"\n检测到的文本内容:")
                            print(f"{'='*60}")
                            print(display_text)
                            print(f"{'='*60}")
                        else:
                            print(f"\n该元素没有文本内容")
                elif element_name != "新闻容器":
                    # 其他元素：显示href（如果是链接）
                    href = info.get('href', '')
                    if href:
                        print(f"\n检测到的链接 (href): {href}")
                    else:
                        print(f"\n该元素没有 href 属性")
                
                confirm = input(f"\n确认使用此元素？(y/n): ").strip().lower()
                if confirm == 'y':
                    return info
                else:
                    continue
            elif choice == '2':
                # 清除：清空所有高亮元素和选中状态
                try:
                    # 直接调用，不使用 safe_evaluate，确保清空操作执行
                    if not self.page.is_closed():
                        await self.page.evaluate("""
                            () => {
                                if (typeof removeAllHighlights === 'function') {
                                    removeAllHighlights();
                                }
                                if (window.highlightedElements) {
                                    window.highlightedElements.forEach(function(el) {
                                        if (el && el.style) {
                                            el.style.outline = '';
                                            el.style.backgroundColor = '';
                                        }
                                    });
                                    window.highlightedElements = [];
                                }
                                window.selectedElement = null;
                                window.selectedElementInfo = null;
                            }
                        """)
                    print("\n✓ 已清空所有高亮元素")
                except Exception as e:
                    print(f"\n⚠️ 清空高亮元素时出错: {e}")
                return None
            elif choice == '3':
                # 父元素
                success = await self.navigate_to_parent()
                if not success:
                    print("\n⚠️ 没有父元素（可能已到达根节点）")
                else:
                    # 重新获取元素信息
                    info = await self.get_element_info()
                    if info:
                        html_already_printed = False  # 导航到新节点，需要重新打印HTML
                    await asyncio.sleep(0.3)
            elif choice == '4':
                # 子元素
                success = await self.navigate_to_child()
                if not success:
                    print("\n⚠️ 没有子元素")
                else:
                    # 重新获取元素信息
                    info = await self.get_element_info()
                    if info:
                        html_already_printed = False  # 导航到新节点，需要重新打印HTML
                    await asyncio.sleep(0.3)
            elif choice == '5':
                # 上一个元素（上一个兄弟节点）
                success = await self.navigate_to_previous_sibling_element()
                if not success:
                    print("\n⚠️ 没有上一个兄弟元素")
                else:
                    # 重新获取元素信息
                    info = await self.get_element_info()
                    if info:
                        html_already_printed = False  # 导航到新节点，需要重新打印HTML
                    await asyncio.sleep(0.3)
            elif choice == '6':
                # 下一个元素（下一个兄弟节点）
                success = await self.navigate_to_next_sibling_element()
                if not success:
                    print("\n⚠️ 没有下一个兄弟元素")
                else:
                    # 重新获取元素信息
                    info = await self.get_element_info()
                    if info:
                        html_already_printed = False  # 导航到新节点，需要重新打印HTML
                    await asyncio.sleep(0.3)
            else:
                print("\n无效选项，请重新选择")
            
            first_loop = False
    
    async def get_element_info(self) -> Dict[str, Any]:
        """获取元素信息，生成定位策略"""
        print("[DEBUG] get_element_info: 开始获取元素信息")
        
        # 首先尝试从当前页面的 selectedElement 获取
        info = await self.safe_evaluate("""
        () => {
            console.log('[DEBUG] get_element_info: 检查 selectedElement');
            console.log('[DEBUG] selectedElement 存在:', !!window.selectedElement);
            console.log('[DEBUG] selectedElement nodeType:', window.selectedElement ? window.selectedElement.nodeType : 'N/A');
            console.log('[DEBUG] selectedElement 在文档中:', window.selectedElement ? document.contains(window.selectedElement) : 'N/A');
            
            // 优先使用当前页面的选中元素
            // 检查 selectedElement 是否存在且有效
            if (window.selectedElement && window.selectedElement.nodeType === 1 && document.contains(window.selectedElement)) {
                console.log('[DEBUG] get_element_info: 从当前页面的 selectedElement 获取');
                const element = window.selectedElement;
                const info = {
                    tag: element.tagName.toLowerCase(),
                    text: element.textContent?.trim().substring(0, 50) || '',
                    class: element.className || '',
                    href: element.href || element.getAttribute('href') || '',
                    xpath: '',
                    tagpath: '',
                    html: ''
                };
                
                // 生成 XPath（不使用 id）
                function getXPath(element) {
                    console.log('[DEBUG] getXPath: 开始生成 xpath, element:', element.tagName);
                    if (!element || element.nodeType !== 1) {
                        console.log('[DEBUG] getXPath: 元素无效或不是元素节点');
                        return '';
                    }
                    if (element === document.documentElement) {
                        console.log('[DEBUG] getXPath: 是 documentElement, 返回 /html');
                        return '/html';
                    }
                    if (element === document.body) {
                        console.log('[DEBUG] getXPath: 是 body, 返回 /html/body');
                        return '/html/body';
                    }
                    if (!element.parentNode) {
                        console.log('[DEBUG] getXPath: 没有 parentNode');
                        return '';
                    }
                    let ix = 0;
                    const siblings = element.parentNode.childNodes;
                    console.log('[DEBUG] getXPath: 父节点:', element.parentNode.tagName, '兄弟节点数量:', siblings.length);
                    for (let i = 0; i < siblings.length; i++) {
                        const sibling = siblings[i];
                        if (sibling === element) {
                            const parentPath = getXPath(element.parentNode);
                            console.log('[DEBUG] getXPath: 找到元素, 索引:', ix, '父路径:', parentPath);
                            if (!parentPath) {
                                console.log('[DEBUG] getXPath: 父路径为空，返回空字符串');
                                return '';
                            }
                            const xpath = parentPath + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
                            console.log('[DEBUG] getXPath: 生成的 xpath:', xpath);
                            return xpath;
                        }
                        if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {
                            ix++;
                        }
                    }
                    console.log('[DEBUG] getXPath: 未找到元素，返回空字符串');
                    return '';
                }
                
                // 生成标签路径
                function getTagPath(element) {
                    const path = [];
                    let current = element;
                    
                    while (current && current !== document && current !== document.documentElement) {
                        if (current.nodeType === 1) {
                            const tagName = current.tagName.toLowerCase();
                            const siblings = current.parentNode ? Array.from(current.parentNode.children) : [];
                            const sameTagSiblings = siblings.filter(s => s.tagName.toLowerCase() === tagName);
                            if (sameTagSiblings.length > 1) {
                                const index = sameTagSiblings.indexOf(current) + 1;
                                path.unshift(`${tagName}[${index}]`);
                            } else {
                                path.unshift(tagName);
                            }
                        }
                        current = current.parentNode;
                    }
                    
                    if (document.documentElement) {
                        path.unshift('html');
                    }
                    
                    return path.join('.');
                }
                
                // 获取HTML
                function getElementHTML(element) {
                    if (!element) return '';
                    return element.outerHTML || element.innerHTML || '';
                }
                
                info.xpath = getXPath(element);
                info.tagpath = getTagPath(element);
                info.html = getElementHTML(element);
                
                console.log('[DEBUG] get_element_info: 生成的 info - xpath:', info.xpath, 'tagpath:', info.tagpath, 'text:', info.text);
                
                return info;
            }
            
            // 如果当前页面没有，尝试从 sessionStorage 恢复
            if (window.selectedElementInfo) {
                console.log('[DEBUG] get_element_info: 从 window.selectedElementInfo 恢复');
                console.log('[DEBUG] selectedElementInfo - xpath:', window.selectedElementInfo.xpath, 'tagpath:', window.selectedElementInfo.tagpath);
                return window.selectedElementInfo;
            }
            
            // 尝试从 sessionStorage 读取
            try {
                const saved = sessionStorage.getItem('__playwright_selected_element');
                if (saved) {
                    console.log('[DEBUG] get_element_info: 从 sessionStorage 读取');
                    const savedInfo = JSON.parse(saved);
                    console.log('[DEBUG] sessionStorage 中的信息 - xpath:', savedInfo.xpath, 'tagpath:', savedInfo.tagpath, 'text:', savedInfo.text);
                    // 确保所有必要字段都存在，如果缺失则重新生成
                    if (savedInfo && !savedInfo.xpath && !savedInfo.tagpath) {
                        console.log('[DEBUG] get_element_info: 保存的信息不完整（xpath 和 tagpath 都为空），返回 null');
                        // 如果保存的信息不完整，返回 null 让用户重新选择
                        return null;
                    }
                    console.log('[DEBUG] get_element_info: 返回 sessionStorage 中的信息');
                    return savedInfo;
                } else {
                    console.log('[DEBUG] get_element_info: sessionStorage 中没有保存的信息');
                }
            } catch(e) {
                console.warn('[DEBUG] get_element_info: 读取 sessionStorage 失败:', e);
            }
            
            console.log('[DEBUG] get_element_info: 所有方法都失败，返回 null');
            return null;
        }
        """, default=None)
        
        if info:
            print(f"[DEBUG] get_element_info: 返回的信息 - xpath: '{info.get('xpath', '')}', tagpath: '{info.get('tagpath', '')}', text: '{info.get('text', '')}'")
        else:
            print("[DEBUG] get_element_info: 返回 None（未找到元素信息）")
        
        return info
    
    def _get_topic_list(self) -> list:
        """从配置文件读取主题列表"""
        selectors_path = "config/selectors.yaml"
        selectors_file = Path(selectors_path)
        
        if selectors_file.exists():
            try:
                with open(selectors_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                
                topic_links = config.get('home_page', {}).get('topic_links', [])
                if isinstance(topic_links, list):
                    return topic_links
            except Exception as e:
                print(f"⚠️ 读取配置文件时出错: {e}")
        
        # 如果配置文件不存在或格式不对，返回默认的13个主题
        default_topics = [
            {"name": "Top stories"},
            {"name": "World"},
            {"name": "Politics"},
            {"name": "Movies"},
            {"name": "Business"},
            {"name": "Economy"},
            {"name": "Personal Finance"},
            {"name": "Digital currencies"},
            {"name": "Finance"},
            {"name": "Technology"},
            {"name": "Internet security"},
            {"name": "Mental health"},
            {"name": "Education"}
        ]
        return default_topics
    
    async def select_topic_links(self):
        """选择主题链接"""
        print("\n=== 选择主题链接 ===")
        
        # 获取主题列表
        topic_list = self._get_topic_list()
        
        # 显示主题选择菜单
        print("\n请选择要配置的主题:")
        for idx, topic in enumerate(topic_list, 1):
            topic_name = topic.get('name', f'主题{idx}')
            has_config = topic.get('method') and topic.get('value')
            status = "✓" if has_config else "○"
            print(f"  {idx:2d}. {status} {topic_name}")
        print(f"  {len(topic_list) + 1:2d}. 返回")
        
        choice = input(f"\n请输入选项 (1-{len(topic_list) + 1}): ").strip()
        
        try:
            choice_num = int(choice)
            if choice_num < 1 or choice_num > len(topic_list) + 1:
                print("无效选项")
                return False
            if choice_num == len(topic_list) + 1:
                return False
        except ValueError:
            print("无效选项")
            return False
        
        # 获取选中的主题
        selected_topic = topic_list[choice_num - 1]
        topic_name = selected_topic.get('name', f'主题{choice_num}')
        
        print(f"\n正在配置主题: {topic_name}")
        print("请在浏览器中点击该主题的链接")
        print("注意：已启用禁止跳转，点击链接不会跳转页面")
        
        # 检查当前标志状态
        current_flag = await self.page.evaluate("() => window.__selecting_topic_link || false")
        print(f"[DEBUG] 注入前 __selecting_topic_link 状态: {current_flag}")
        
        # 注入禁止跳转的逻辑（仅用于选项1）
        print("[DEBUG] 开始注入禁止跳转逻辑...")
        await self.page.evaluate("""
            () => {
                // 设置标志，表示正在选择主题链接
                window.__selecting_topic_link = true;
                console.log('[DEBUG] 设置 __selecting_topic_link = true');
                
                // 创建链接点击拦截器（仅用于选择主题链接）
                // 移除旧的拦截器（如果存在）
                if (window.__topic_link_interceptor) {
                    document.removeEventListener('click', window.__topic_link_interceptor, true);
                    window.__topic_link_interceptor = null;
                    console.log('[DEBUG] 移除旧的拦截器');
                }
                
                window.__topic_link_interceptor = function(e) {
                    const target = e.target;
                    const linkElement = target.tagName === 'A' ? target : target.closest('a');
                    console.log('[DEBUG] 拦截器触发 - target:', target.tagName, 'linkElement:', !!linkElement, '__selecting_topic_link:', window.__selecting_topic_link);
                    if (linkElement && window.__selecting_topic_link) {
                        console.log('[DEBUG] 拦截器阻止链接跳转 - href:', linkElement.href);
                        // 阻止链接跳转（默认行为）
                        e.preventDefault();
                        // 不阻止事件传播，让元素选择处理函数能够执行
                        // 但标记事件已被处理，避免后续处理函数再次允许跳转
                        e.__topic_link_prevented = true;
                        console.log('[DEBUG] 拦截器已阻止默认行为并标记事件');
                    }
                };
                // 在捕获阶段拦截链接点击（使用捕获阶段，确保在其他处理函数之前执行）
                document.addEventListener('click', window.__topic_link_interceptor, true);
                console.log('[DEBUG] 拦截器已注册到捕获阶段');
            }
        """)
        
        # 验证注入是否成功
        flag_status = await self.page.evaluate("() => window.__selecting_topic_link || false")
        interceptor_status = await self.page.evaluate("() => !!window.__topic_link_interceptor")
        print(f"[DEBUG] 注入后 __selecting_topic_link: {flag_status}, __topic_link_interceptor: {interceptor_status}")
        print("[DEBUG] 禁止跳转逻辑注入完成")
        
        try:
            # 使用统一的等待元素选择流程
            info = await self.wait_for_element_selection(f"主题链接_{topic_name}", wait_time=1.0, re_inject_script=False)
            if not info:
                return False
            
            # 使用统一的确认流程（HTML已经打印，传入True避免重复打印）
            info = await self.confirm_element_selection(f"主题链接_{topic_name}", html_already_printed=True)
            if not info:
                return False
            
            # 显示定位信息
            self.show_location_info(info)
            
            # 选择定位方式
            method = input("\n选择定位方式 (tagpath/xpath/text): ").strip().lower()
            if method not in ['tagpath', 'xpath', 'text']:
                method = 'tagpath'
            
            if method == 'tagpath':
                value = info.get('tagpath', '') or info.get('xpath', '')
            elif method == 'xpath':
                value = info.get('xpath', '')
            else:
                value = info.get('text', '')
            
            # 注册已选元素
            if not self._check_duplicate(info, f"主题链接_{topic_name}"):
                self._register_element(info, f"主题链接_{topic_name}")
            
            # 直接更新配置文件中的对应节点
            self.update_config_node("主题链接", method, value, topic_name=topic_name)
            
            await self.page.evaluate("removeAllHighlights()")
            
            print(f"\n✓ 主题链接 '{topic_name}' 已保存")
            return True
        finally:
            # 移除禁止跳转的逻辑（确保在异常情况下也能移除）
            print("[DEBUG] 开始移除禁止跳转逻辑...")
            await self.page.evaluate("""
                () => {
                    if (window.__topic_link_interceptor) {
                        document.removeEventListener('click', window.__topic_link_interceptor, true);
                        window.__topic_link_interceptor = null;
                        console.log('[DEBUG] 移除拦截器');
                    }
                    // 清除选择主题链接的标志
                    window.__selecting_topic_link = false;
                    console.log('[DEBUG] 清除 __selecting_topic_link 标志');
                }
            """)
            print("[DEBUG] 禁止跳转逻辑移除完成")
    
    async def select_news_container(self):
        """选择新闻容器"""
        print("\n=== 选择新闻容器 ===")
        print("请导航到主题页面（如 World 页面）")
        print("请在浏览器中点击新闻列表的容器区域（任意一个新闻项）")
        print("注意：选择后将自动滚动加载所有新闻项，并高亮显示所有容器")
        
        # 使用统一的等待元素选择流程
        info = await self.wait_for_element_selection("新闻容器", wait_time=0.5)
        if not info:
            return False
        
        # 使用统一的确认流程（HTML已经打印，传入True避免重复打印）
        info = await self.confirm_element_selection("新闻容器", html_already_printed=True)
        if not info:
            return False
        
        # 对于新闻容器，需要滚动加载所有项并获取所有兄弟元素
        print("\n正在滚动加载所有新闻项（等待网络请求完成）...")
        scroll_attempts = await self.safe_evaluate("scrollToBottomUntilNoNewContent()", default=0)
        print(f"滚动完成，共尝试 {scroll_attempts} 次")
        
        # 向用户确认定位方式
        print("\n请选择定位兄弟元素的方式：")
        print("  1. 获取父元素的所有子元素（推荐，适用于新闻列表）")
        print("  2. 只获取相同标签名的兄弟元素")
        choice = input("\n请输入选项 (1-2，默认1): ").strip() or '1'
        use_parent_children = (choice == '1')
        
        # 获取所有兄弟容器并高亮
        print("\n正在查找所有新闻容器...")
        
        # 首先尝试恢复 selectedElement（如果丢失了）
        restore_result = await self.safe_evaluate("""
            () => {
                console.log('[DEBUG] 尝试恢复 selectedElement...');
                console.log('[DEBUG] selectedElement 存在:', !!window.selectedElement);
                console.log('[DEBUG] selectedElementInfo 存在:', !!window.selectedElementInfo);
                
                // 如果 selectedElement 存在且有效，直接返回
                if (window.selectedElement && document.contains(window.selectedElement)) {
                    console.log('[DEBUG] selectedElement 已存在且有效');
                    return { restored: false, reason: 'already_exists' };
                }
                
                // 尝试从 selectedElementInfo 恢复
                if (window.selectedElementInfo && window.selectedElementInfo.xpath) {
                    try {
                        console.log('[DEBUG] 尝试使用 xpath 恢复:', window.selectedElementInfo.xpath);
                        const result = document.evaluate(
                            window.selectedElementInfo.xpath,
                            document,
                            null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE,
                            null
                        );
                        const element = result.singleNodeValue;
                        if (element && document.contains(element)) {
                            window.selectedElement = element;
                            console.log('[DEBUG] 使用 xpath 成功恢复 selectedElement');
                            return { restored: true, method: 'xpath', tag: element.tagName };
                        } else {
                            console.log('[DEBUG] xpath 恢复失败，元素不存在或不在文档中');
                        }
                    } catch(e) {
                        console.log('[DEBUG] xpath 恢复出错:', e);
                    }
                }
                
                // 尝试使用 tagpath 恢复
                if (window.selectedElementInfo && window.selectedElementInfo.tagpath) {
                    try {
                        console.log('[DEBUG] 尝试使用 tagpath 恢复:', window.selectedElementInfo.tagpath);
                        const parts = window.selectedElementInfo.tagpath.split('.');
                        let elements = [document];
                        
                        for (let i = 0; i < parts.length; i++) {
                            const part = parts[i];
                            const match = part.match(/^(\w+)(?:\[(\d+)\])?$/);
                            if (!match) continue;
                            
                            const tagName = match[1];
                            const index = match[2] ? parseInt(match[2]) - 1 : null;
                            const nextElements = [];
                            
                            for (const parent of elements) {
                                const children = Array.from(parent.getElementsByTagName(tagName));
                                if (index !== null) {
                                    if (children[index]) {
                                        nextElements.push(children[index]);
                                    }
                                } else {
                                    nextElements.push(...children);
                                }
                            }
                            
                            elements = nextElements;
                        }
                        
                        if (elements.length > 0 && document.contains(elements[0])) {
                            window.selectedElement = elements[0];
                            console.log('[DEBUG] 使用 tagpath 成功恢复 selectedElement');
                            return { restored: true, method: 'tagpath', tag: elements[0].tagName };
                        } else {
                            console.log('[DEBUG] tagpath 恢复失败，元素不存在或不在文档中');
                        }
                    } catch(e) {
                        console.log('[DEBUG] tagpath 恢复出错:', e);
                    }
                }
                
                console.log('[DEBUG] 无法恢复 selectedElement');
                return { restored: false, reason: 'no_info_or_failed' };
            }
        """, default=None)
        
        if restore_result:
            if restore_result.get('restored'):
                print(f"[DEBUG] ✓ 成功恢复 selectedElement (方法: {restore_result.get('method')}, 标签: {restore_result.get('tag')})")
            else:
                print(f"[DEBUG] ⚠️ 未能恢复 selectedElement (原因: {restore_result.get('reason')})")
        
        # 调试：检查 selectedElement 状态
        debug_info = await self.safe_evaluate("""
            () => {
                return {
                    hasSelectedElement: !!window.selectedElement,
                    selectedElementTag: window.selectedElement ? window.selectedElement.tagName : null,
                    selectedElementInDoc: window.selectedElement ? document.contains(window.selectedElement) : false,
                    hasParent: window.selectedElement && window.selectedElement.parentNode ? true : false,
                    parentTag: window.selectedElement && window.selectedElement.parentNode ? window.selectedElement.parentNode.tagName : null,
                    parentChildrenCount: window.selectedElement && window.selectedElement.parentNode ? window.selectedElement.parentNode.children.length : 0
                };
            }
        """, default=None)
        print(f"[DEBUG] 元素状态检查:")
        print(f"  - selectedElement 存在: {debug_info.get('hasSelectedElement') if debug_info else 'N/A'}")
        print(f"  - selectedElement 标签: {debug_info.get('selectedElementTag') if debug_info else 'N/A'}")
        print(f"  - selectedElement 在文档中: {debug_info.get('selectedElementInDoc') if debug_info else 'N/A'}")
        print(f"  - 父元素存在: {debug_info.get('hasParent') if debug_info else 'N/A'}")
        print(f"  - 父元素标签: {debug_info.get('parentTag') if debug_info else 'N/A'}")
        print(f"  - 父元素子元素数量: {debug_info.get('parentChildrenCount') if debug_info else 'N/A'}")
        
        # 调试：检查 highlightAllSiblings 函数是否存在
        has_highlight_func = await self.safe_evaluate("() => typeof highlightAllSiblings === 'function'", default=False)
        print(f"[DEBUG] highlightAllSiblings 函数存在: {has_highlight_func}")
        
        if not has_highlight_func:
            print("[DEBUG] ⚠️ highlightAllSiblings 函数不存在，可能脚本未正确注入")
        
        sibling_count = await self.safe_evaluate(f"""
            () => {{
                console.log('[DEBUG] 开始查找兄弟元素...');
                console.log('[DEBUG] selectedElement:', !!window.selectedElement);
                console.log('[DEBUG] use_parent_children: {str(use_parent_children).lower()}');
                
                if (!window.selectedElement) {{
                    console.log('[DEBUG] selectedElement 不存在，返回 0');
                    return 0;
                }}
                
                console.log('[DEBUG] selectedElement 标签:', window.selectedElement.tagName);
                console.log('[DEBUG] selectedElement 在文档中:', document.contains(window.selectedElement));
                
                if (!document.contains(window.selectedElement)) {{
                    console.log('[DEBUG] selectedElement 不在文档中，返回 0');
                    return 0;
                }}
                
                if (!window.selectedElement.parentNode) {{
                    console.log('[DEBUG] 父元素不存在，返回 0');
                    return 0;
                }}
                
                const parent = window.selectedElement.parentNode;
                console.log('[DEBUG] 父元素标签:', parent.tagName);
                console.log('[DEBUG] 父元素子元素数量:', parent.children ? parent.children.length : 0);
                
                if (typeof highlightAllSiblings !== 'function') {{
                    console.log('[DEBUG] highlightAllSiblings 函数不存在');
                    return 0;
                }}
                
                const count = highlightAllSiblings(window.selectedElement, {str(use_parent_children).lower()});
                console.log('[DEBUG] highlightAllSiblings 返回:', count);
                return count;
            }}
        """, default=0)
        print(f"[DEBUG] highlightAllSiblings 返回的兄弟元素数量: {sibling_count}")
        print(f"找到 {sibling_count} 个新闻容器（已高亮显示）")
        
        # 生成能够匹配所有兄弟容器的选择器
        if use_parent_children:
            # 如果使用父元素的所有子元素，需要定位到父元素，然后选择所有直接子元素
            # 获取父元素的tagpath或xpath，并生成匹配所有直接子元素的选择器
            print(f"[DEBUG] 开始获取父元素信息...")
            parent_info = await self.safe_evaluate("""
                () => {
                    console.log('[DEBUG] 获取父元素信息 - 开始');
                    console.log('[DEBUG] selectedElement 存在:', !!window.selectedElement);
                    
                    if (!window.selectedElement) {
                        console.log('[DEBUG] selectedElement 不存在，返回 null');
                        return null;
                    }
                    
                    if (!window.selectedElement.parentNode) {
                        console.log('[DEBUG] 父元素不存在，返回 null');
                        return null;
                    }
                    
                    const parent = window.selectedElement.parentNode;
                    console.log('[DEBUG] 父元素 nodeType:', parent.nodeType);
                    console.log('[DEBUG] 父元素 tagName:', parent.tagName);
                    console.log('[DEBUG] 父元素子元素数量:', parent.children ? parent.children.length : 0);
                    
                    if (parent.nodeType !== 1) {
                        console.log('[DEBUG] 父元素不是元素节点，返回 null');
                        return null; // 不是元素节点
                    }
                    
                    // 生成父元素的tagpath
                    function getTagPath(element) {
                        const path = [];
                        let current = element;
                        while (current && current !== document && current !== document.documentElement) {
                            if (current.nodeType === 1) {
                                const tagName = current.tagName.toLowerCase();
                                const siblings = current.parentNode ? Array.from(current.parentNode.children) : [];
                                const sameTagSiblings = siblings.filter(s => s.tagName.toLowerCase() === tagName);
                                if (sameTagSiblings.length > 1) {
                                    const index = sameTagSiblings.indexOf(current) + 1;
                                    path.unshift(`${tagName}[${index}]`);
                                } else {
                                    path.unshift(tagName);
                                }
                            }
                            current = current.parentNode;
                        }
                        if (document.documentElement) {
                            path.unshift('html');
                        }
                        return path.join('.');
                    }
                    
                    // 生成父元素的xpath（用于定位父元素本身）
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
                    
                    const parentXPath = getXPath(parent);
                    console.log('[DEBUG] 生成的父元素 XPath:', parentXPath);
                    
                    // 生成匹配所有直接子元素的XPath
                    const childrenXPath = parentXPath ? parentXPath + '/*' : '';
                    console.log('[DEBUG] 生成的子元素 XPath:', childrenXPath);
                    
                    const tagpath = getTagPath(parent);
                    console.log('[DEBUG] 生成的父元素 TagPath:', tagpath);
                    
                    const result = {
                        tagpath: tagpath,
                        xpath: childrenXPath,  // 直接返回匹配所有子元素的XPath
                        parent_xpath: parentXPath  // 也保存父元素的XPath，以备后用
                    };
                    
                    console.log('[DEBUG] 返回的父元素信息:', JSON.stringify(result));
                    return result;
                }
            """, default=None)
            
            print(f"[DEBUG] 获取到的父元素信息:")
            if parent_info:
                print(f"  - parent_xpath: {parent_info.get('parent_xpath', 'N/A')}")
                print(f"  - xpath (子元素): {parent_info.get('xpath', 'N/A')}")
                print(f"  - tagpath: {parent_info.get('tagpath', 'N/A')}")
            else:
                print(f"  - ⚠️ 未能获取父元素信息")
            
            if parent_info:
                # 优先使用XPath，因为它可以直接匹配所有子元素
                current_xpath = parent_info.get('xpath', '')
                current_tagpath = parent_info.get('tagpath', '')
                
                print(f"[DEBUG] 处理父元素信息:")
                print(f"  - current_xpath: {current_xpath}")
                print(f"  - current_tagpath: {current_tagpath}")
                
                if current_xpath:
                    # 使用XPath匹配所有直接子元素
                    value = current_xpath
                    method = 'xpath'
                    print(f"[DEBUG] 使用 XPath 方式: {value}")
                elif current_tagpath:
                    # 如果有tagpath，转换为XPath来匹配所有子元素
                    # 将tagpath转换为XPath，然后加上 /* 来匹配所有直接子元素
                    parts = current_tagpath.split('.')
                    xpath_parts = []
                    for part in parts:
                        xpath_parts.append(part)
                    # 构建XPath：/html/body/div[2]/section/*
                    xpath = '/' + '/'.join(xpath_parts) + '/*'
                    value = xpath
                    method = 'xpath'
                else:
                    # 如果无法获取父元素信息，使用原来的逻辑（去掉最后一个索引）
                    current_tagpath = info.get('tagpath', '')
                    if current_tagpath:
                        parts = current_tagpath.split('.')
                        if parts:
                            # 去掉最后一个索引，然后转换为XPath匹配所有子元素
                            last_part = parts[-1]
                            if '[' in last_part:
                                tag_name = last_part.split('[')[0]
                                parts[-1] = tag_name
                            # 转换为XPath
                            xpath_parts = ['html']  # 从html开始
                            for part in parts[1:]:  # 跳过第一个 'html'（如果有）
                                xpath_parts.append(part)
                            xpath = '/' + '/'.join(xpath_parts) + '/*'
                            value = xpath
                            method = 'xpath'
                        else:
                            # 如果无法转换，使用tagpath
                            value = current_tagpath
                            method = 'tagpath'
                    else:
                        xpath = info.get('xpath', '')
                        if xpath:
                            # 去掉最后一个索引，然后加上 /* 来匹配所有子元素
                            parts = xpath.split('/')
                            if parts:
                                last_part = parts[-1]
                                if '[' in last_part:
                                    tag_name = last_part.split('[')[0]
                                    parts[-1] = tag_name
                                value = '/'.join(parts) + '/*'
                            else:
                                value = xpath + '/*'
                        else:
                            value = info.get('text', '')
                        method = 'xpath' if xpath else 'text'
            else:
                # 无法获取父元素信息，使用原来的逻辑
                print(f"[DEBUG] ⚠️ 无法获取父元素信息，使用备用逻辑")
                print(f"[DEBUG] 当前元素信息:")
                print(f"  - tagpath: {info.get('tagpath', 'N/A')}")
                print(f"  - xpath: {info.get('xpath', 'N/A')}")
                current_tagpath = info.get('tagpath', '')
                if current_tagpath:
                    parts = current_tagpath.split('.')
                    if parts:
                        last_part = parts[-1]
                        if '[' in last_part:
                            tag_name = last_part.split('[')[0]
                            parts[-1] = tag_name
                        # 转换为XPath匹配所有子元素
                        xpath_parts = []
                        for part in parts[1:]:  # 跳过 'html'
                            xpath_parts.append(part)
                        xpath = '/' + '/'.join(xpath_parts) + '/*'
                        value = xpath
                        method = 'xpath'
                else:
                    xpath = info.get('xpath', '')
                    if xpath:
                        parts = xpath.split('/')
                        if parts:
                            last_part = parts[-1]
                            if '[' in last_part:
                                tag_name = last_part.split('[')[0]
                                parts[-1] = tag_name
                            value = '/'.join(parts) + '/*'
                        else:
                            value = xpath + '/*'
                    else:
                        value = info.get('text', '')
                    method = 'xpath' if xpath else 'text'
        else:
            # 如果只获取相同标签的兄弟元素，去掉最后一个索引
            current_tagpath = info.get('tagpath', '')
            if current_tagpath:
                parts = current_tagpath.split('.')
                if parts:
                    last_part = parts[-1]
                    if '[' in last_part:
                        tag_name = last_part.split('[')[0]
                        parts[-1] = tag_name
                    value = '.'.join(parts)
                else:
                    value = current_tagpath
                method = 'tagpath'
            else:
                xpath = info.get('xpath', '')
                if xpath:
                    parts = xpath.split('/')
                    if parts:
                        last_part = parts[-1]
                        if '[' in last_part:
                            tag_name = last_part.split('[')[0]
                            parts[-1] = tag_name
                        value = '/'.join(parts)
                    else:
                        value = xpath
                else:
                    value = info.get('text', '')
                method = 'xpath' if xpath else 'text'
        
        # 显示定位信息
        print(f"\n生成的定位方式: {method}")
        print(f"定位值: {value}")
        if use_parent_children:
            print(f"此选择器将定位到父元素，匹配所有 {sibling_count} 个子元素")
        else:
            print(f"此选择器将匹配所有 {sibling_count} 个相同标签的兄弟元素")
        
        confirm = input("\n确认使用此选择器？(y/n): ").strip().lower()
        if confirm != 'y':
            await self.safe_evaluate("removeAllHighlights()")
            return False
        
        if 'topic_page' not in self.config:
            self.config['topic_page'] = {}
        self.config['topic_page']['news_container'] = {
            'method': method,
            'value': value
        }
        
        if not self._check_duplicate(info, "新闻容器"):
            self._register_element(info, "新闻容器")
        
        # 直接更新配置文件中的对应节点
        self.update_config_node("新闻容器", method, value)
        
        await self.safe_evaluate("removeAllHighlights()")
        print("\n✓ 新闻容器已保存")
        return True
    
    async def select_card_link(self, index: int):
        """选择卡片链接（来源链接）"""
        print(f"\n=== 选择卡片链接 {index} ===")
        print(f"请在浏览器中点击卡片中的来源链接 {index}")
        
        # 使用统一的等待元素选择流程
        info = await self.wait_for_element_selection(f"卡片链接{index}", wait_time=0.5)
        if not info:
            return False
        
        # 使用统一的确认流程（HTML已经打印，传入True避免重复打印）
        info = await self.confirm_element_selection(f"卡片链接{index}", html_already_printed=True)
        if not info:
            return False
        
        # 显示定位信息
        self.show_location_info(info)
        
        method = input("\n选择定位方式 (tagpath/xpath/text): ").strip().lower() or 'tagpath'
        if method == 'tagpath':
            value = info.get('tagpath', '') or info.get('xpath', '')
        elif method == 'xpath':
            value = info.get('xpath', '')
        else:
            value = info.get('text', '')
        
        if 'topic_page' not in self.config:
            self.config['topic_page'] = {}
        if 'sources' not in self.config['topic_page']:
            self.config['topic_page']['sources'] = []
        
        # 查找或创建对应的source配置
        source_config = None
        for src in self.config['topic_page']['sources']:
            if src.get('index') == index - 1:
                source_config = src
                break
        
        if not source_config:
            source_config = {
                'index': index - 1,
                'link': {}
            }
            self.config['topic_page']['sources'].append(source_config)
        
        source_config['link'] = {
            'method': method,
            'value': value
        }
        
        if not self._check_duplicate(info, f"卡片链接{index}"):
            self._register_element(info, f"卡片链接{index}")
        
        # 直接更新配置文件中的对应节点
        self.update_config_node(f"卡片链接{index}", method, value)
        
        await self.page.evaluate("removeAllHighlights()")
        print(f"\n✓ 卡片链接 {index} 已保存")
        return True
    
    def extract_domain_from_url(self, url: str) -> str:
        """从URL中提取域名"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            # 移除 www. 前缀
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception as e:
            print(f"⚠️ 提取域名失败: {e}")
            return ""
    
    async def _check_and_confirm_domain_config(self, domain: str) -> bool:
        """检查域名配置并确认是否继续配置
        
        Args:
            domain: 要检查的域名
            
        Returns:
            bool: True 表示继续配置，False 表示取消配置
        """
        # 检查配置文件中是否已存在该域名
        selectors_path = "config/selectors.yaml"
        selectors_file = Path(selectors_path)
        
        if selectors_file.exists():
            try:
                import yaml
                with open(selectors_file, 'r', encoding='utf-8') as f:
                    existing_config = yaml.safe_load(f) or {}
                
                third_party_news = existing_config.get('third_party_news', {})
                if domain in third_party_news:
                    # 显示现有配置
                    domain_config = third_party_news[domain]
                    print(f"\n⚠️ 检测到域名 {domain} 已存在配置:")
                    print(f"{'='*60}")
                    for key, value in domain_config.items():
                        # 只处理字典类型的配置项（title, content, cover, author）
                        if isinstance(value, dict):
                            method = value.get('method', '')
                            val = value.get('value', '')
                            if method and val:
                                print(f"  {key}: {method} = {val[:100]}{'...' if len(val) > 100 else ''}")
                            else:
                                print(f"  {key}: 未配置")
                        # 忽略非字典类型的字段（如 remark 等）
                    print(f"{'='*60}")
                    print("\n是否要重新配置此域名？(y/n): ", end='')
                    confirm = input().strip().lower()
                    if confirm != 'y':
                        print("已取消操作")
                        return False
            except Exception as e:
                print(f"⚠️ 读取配置文件时出错: {e}，将继续创建新配置")
        
        return True
    
    async def _show_third_party_element_menu(self, domain: str) -> None:
        """显示第三方新闻元素配置菜单
        
        Args:
            domain: 域名
        """
        # 显示子选项菜单
        while True:
                print("\n请选择要配置的元素:")
                print("  1. 标题")
                print("  2. 内容")
                print("  3. 封面")
                print("  4. 作者")
                print("  5. 完成配置")
                choice = input("\n请输入选项 (1-5): ").strip()
                
                if choice == '1':
                    await self.select_third_party_element("标题", domain)
                elif choice == '2':
                    await self.select_third_party_element("内容", domain)
                elif choice == '3':
                    await self.select_third_party_element("封面", domain)
                elif choice == '4':
                    await self.select_third_party_element("作者", domain)
                elif choice == '5':
                    break
                else:
                    print("无效选项，请重新选择")
    
    async def select_third_party_news(self):
        """选择第三方新闻配置"""
        print("\n=== 配置第三方新闻 ===")
        print("请在 Google News 页面点击一个新闻链接，将在新标签页中打开并自动配置")
        print("等待您点击链接...")
        
        # 设置等待标志，触发后续流程
        self.waiting_for_third_party_news = True
        
        # 等待用户点击链接并等待 _handle_new_page 处理完成
        # 循环等待，直到 waiting_for_third_party_news 变为 False
        max_wait_time = 300  # 最多等待5分钟
        wait_count = 0
        while self.waiting_for_third_party_news and wait_count < max_wait_time:
            await asyncio.sleep(0.5)
            wait_count += 1
        
        if self.waiting_for_third_party_news:
            print("\n⚠️ 等待超时，未检测到新标签页或配置未完成")
            self.waiting_for_third_party_news = False
            return False
        
        print("\n✓ 第三方新闻配置已完成")
        return True
    
    async def select_third_party_element(self, element_type: str, domain: str):
        """选择第三方新闻的元素（标题/内容/封面/作者）"""
        print(f"\n=== 选择{element_type} ===")
        print(f"请在浏览器中点击{element_type}元素")
        
        # 使用统一的等待元素选择流程
        info = await self.wait_for_element_selection(f"{domain}_{element_type}", wait_time=0.5)
        if not info:
            return False
        
        # 使用统一的确认流程
        info = await self.confirm_element_selection(f"{domain}_{element_type}", html_already_printed=True)
        if not info:
            return False
        
        # 显示定位信息
        self.show_location_info(info)
        
        method = input("\n选择定位方式 (tagpath/xpath/text): ").strip().lower() or 'tagpath'
        if method == 'tagpath':
            value = info.get('tagpath', '') or info.get('xpath', '')
        elif method == 'xpath':
            value = info.get('xpath', '')
        else:
            value = info.get('text', '')
        
        # 确保 value 不为空
        if not value:
            print(f"⚠️ 警告：无法获取{element_type}的定位值，请重新选择")
            return False
        
        # 更新配置
        self.update_third_party_config(domain, element_type, method, value)
        
        if not self._check_duplicate(info, f"{domain}_{element_type}"):
            self._register_element(info, f"{domain}_{element_type}")
        
        await self.safe_evaluate("removeAllHighlights()")
        print(f"\n✓ {element_type}已保存")
        return True
    
    def update_third_party_config(self, domain: str, element_type: str, method: str, value: str):
        """更新第三方新闻配置"""
        output_path = "config/selectors.yaml"
        output_file = Path(output_path)
        
        # 读取现有配置
        existing_config = {}
        if output_file.exists():
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    existing_config = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"⚠️ 读取现有配置失败: {e}，将创建新配置")
        
        # 创建第三方新闻配置结构
        if 'third_party_news' not in existing_config:
            existing_config['third_party_news'] = {}
        
        if domain not in existing_config['third_party_news']:
            existing_config['third_party_news'][domain] = {
                'title': {'method': '', 'value': ''},
                'content': {'method': '', 'value': ''},
                'cover': {'method': '', 'value': ''},
                'author': {'method': '', 'value': ''}
            }
        
        # 映射元素类型到配置键
        element_key_map = {
            '标题': 'title',
            '内容': 'content',
            '封面': 'cover',
            '作者': 'author'
        }
        
        element_key = element_key_map.get(element_type, element_type.lower())
        
        # 调试信息
        print(f"\n[调试] 准备保存配置:")
        print(f"  - domain: {domain}")
        print(f"  - element_type: {element_type}")
        print(f"  - element_key: {element_key}")
        print(f"  - method: {method}")
        print(f"  - value: {value[:100] if len(value) > 100 else value}")
        
        existing_config['third_party_news'][domain][element_key] = {
            'method': method,
            'value': value
        }
        
        # 保存更新后的配置
        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            # 确保保留所有现有配置（包括 home_page 和 topic_page）
            with open(output_file, 'w', encoding='utf-8') as f:
                yaml.dump(existing_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            print(f"✓ 配置已更新到: {output_path}")
            
            # 验证保存是否成功
            try:
                # 等待文件写入完成
                import time
                time.sleep(0.1)
                
                with open(output_file, 'r', encoding='utf-8') as f:
                    saved_config = yaml.safe_load(f) or {}
                
                # 检查所有主要配置是否都存在
                if 'home_page' not in saved_config:
                    print(f"⚠️ 警告：保存后 home_page 配置丢失")
                if 'topic_page' not in saved_config:
                    print(f"⚠️ 警告：保存后 topic_page 配置丢失")
                if 'third_party_news' not in saved_config:
                    print(f"⚠️ 警告：保存后 third_party_news 配置丢失")
                
                # 检查具体保存的值
                saved_value = saved_config.get('third_party_news', {}).get(domain, {}).get(element_key, {}).get('value', '')
                saved_method = saved_config.get('third_party_news', {}).get(domain, {}).get(element_key, {}).get('method', '')
                
                if saved_value == value and saved_method == method:
                    print(f"✓ 验证：{element_type}配置已成功保存 (method={saved_method}, value长度={len(saved_value)})")
                else:
                    print(f"⚠️ 警告：保存后验证失败")
                    print(f"  期望: method={method}, value长度={len(value)}")
                    print(f"  实际: method={saved_method}, value长度={len(saved_value)}")
                    print(f"  value匹配: {saved_value == value}")
            except Exception as e:
                print(f"⚠️ 验证保存结果时出错: {e}")
                import traceback
                traceback.print_exc()
        except Exception as e:
            print(f"❌ 保存配置失败: {e}")
            import traceback
            traceback.print_exc()
    
    async def select_news_elements_old(self):
        """引导用户选择新闻元素"""
        print("\n=== 选择新闻元素 ===")
        print("请导航到主题页面（如 World 页面）")
        input("准备好后按 Enter 继续...")
        
        # 选择新闻容器
        print("\n1. 请点击新闻列表的容器区域")
        input("点击后按 Enter 继续...")
        
        # 等待一下，确保点击事件已处理
        await asyncio.sleep(0.5)
        
        # 调试：检查是否有选中的元素
        debug_info = await self.page.evaluate("""
        () => {
            return {
                hasSelectedElement: !!window.selectedElement,
                hasSelectedElementInfo: !!window.selectedElementInfo,
                sessionStorageValue: sessionStorage.getItem('__playwright_selected_element')
            };
        }
        """)
        print(f"\n[调试] 元素状态: {debug_info}")
        
        container_info = await self.get_element_info()
        if not container_info:
            print("\n⚠️ 未检测到选中的元素")
            print("可能的原因：")
            print("  1. 点击事件被阻止")
            print("  2. 页面已跳转，元素信息丢失")
            print("  3. 浏览器阻止了脚本执行")
            print("\n请尝试：")
            print("  1. 重新点击容器区域")
            print("  2. 确保点击后页面没有跳转")
            retry = input("\n是否重试？(y/n): ").strip().lower()
            if retry == 'y':
                return await self.select_news_elements()
            return
        
        # 显示元素信息
        print(f"\n检测到的元素信息:")
        print(f"  标签: {container_info.get('tag', 'N/A')}")
        print(f"  文本: {container_info.get('text', 'N/A')[:50]}")
        print(f"  标签路径: {container_info.get('tagpath', 'N/A')}")
        print(f"  XPath: {container_info.get('xpath', 'N/A')}")
        
        # 高亮元素
        tagpath = container_info.get('tagpath', '')
        xpath = container_info.get('xpath', '')
        text = container_info.get('text', '')
        
        if tagpath:
            await self.page.evaluate(f"highlightAllByTagPath(`{tagpath}`)")
        elif xpath:
            await self.page.evaluate(f"highlightAllByXPath(`{xpath}`)")
        elif text:
            await self.page.evaluate(f"highlightAllByText(`{text}`)")
        print(f"\n已高亮所有类似元素，请确认是否正确")
        
        # 检测重复
        if self._check_duplicate(container_info, "新闻容器"):
            choice = input("\n选择操作: (r)重新选择 / (c)继续使用 / (d)清除重复项 / (clear)清空所有标识: ").strip().lower()
            if choice == 'r':
                return await self.select_news_elements()
            elif choice == 'd':
                # 清除重复项（当前这个）
                self.clear_element(container_info, "新闻容器")
                # 继续注册当前元素
            elif choice == 'clear':
                self.clear_selected_elements()
                return await self.select_news_elements()
            # 继续使用，不注册（避免重复注册）
        
        method = input("选择定位方式 (tagpath/xpath/text/clear): ").strip().lower() or 'tagpath'
        if method in ['clear', 'clean']:
            # 清除当前选择的内容
            self.clear_element(container_info, "新闻容器")
            # 清除页面高亮
            await self.page.evaluate("removeAllHighlights()")
            # 重新开始选择新闻容器
            print("\n1. 请点击新闻列表的容器区域")
            input("点击后按 Enter 继续...")
            await asyncio.sleep(0.5)
            return await self.select_news_elements()
        if method == 'tagpath':
            value = container_info.get('tagpath', container_info.get('xpath', ''))
        elif method == 'xpath':
            value = container_info.get('xpath', '')
        else:
            value = container_info.get('text', '')
        self.config['topic_page'] = {
            'news_container': {
                'method': method,
                'value': value
            }
        }
        
        # 注册已选元素
        self._register_element(container_info, "新闻容器")
        
        # 选择新闻项
        print("\n2. 请点击一个新闻项（整个新闻卡片）")
        input("点击后按 Enter 继续...")
        await asyncio.sleep(0.5)
        item_info = await self.get_element_info()
        if item_info:
            # 检测重复
            if self._check_duplicate(item_info, "新闻项"):
                choice = input("\n选择操作: (r)重新选择 / (c)继续使用 / (d)清除重复项 / (clear)清空所有标识: ").strip().lower()
                if choice == 'r':
                    # 清除页面高亮
                    await self.page.evaluate("removeAllHighlights()")
                    # 重新选择新闻项
                    print("\n2. 请点击一个新闻项（整个新闻卡片）")
                    input("点击后按 Enter 继续...")
                    await asyncio.sleep(0.5)
                    item_info = await self.get_element_info()
                    if not item_info:
                        return
                elif choice == 'd':
                    # 清除重复项（当前这个）
                    self.clear_element(item_info, "新闻项")
                    # 清除页面高亮
                    await self.page.evaluate("removeAllHighlights()")
                elif choice in ['clear', 'clean']:
                    self.clear_selected_elements()
                    # 清除页面高亮
                    await self.page.evaluate("removeAllHighlights()")
                    return await self.select_news_elements()
            
            method = input("选择定位方式 (tagpath/xpath/text/clear): ").strip().lower() or 'tagpath'
            if method in ['clear', 'clean']:
                # 清除当前选择的内容
                self.clear_element(item_info, "新闻项")
                # 清除页面高亮
                await self.page.evaluate("removeAllHighlights()")
                # 重新开始选择新闻项
                print("\n2. 请点击一个新闻项（整个新闻卡片）")
                input("点击后按 Enter 继续...")
                await asyncio.sleep(0.5)
                # 继续处理，不返回
                item_info = await self.get_element_info()
                if not item_info:
                    return
                # 重新获取定位方式
                method = input("选择定位方式 (tagpath/xpath/text/clear): ").strip().lower() or 'tagpath'
                if method in ['clear', 'clean']:
                    # 如果再次选择clear，递归处理
                    return await self.select_news_elements()
            if method == 'tagpath':
                item_value = item_info.get('tagpath', item_info.get('xpath', ''))
            elif method == 'xpath':
                item_value = item_info.get('xpath', '')
            else:
                item_value = item_info.get('text', '')
            self.config['topic_page']['news_item'] = {
                'method': method,
                'value': item_value
            }
            # 注册已选元素
            self._register_element(item_info, "新闻项")
        
        # 选择标题
        print("\n3. 请点击新闻标题")
        input("点击后按 Enter 继续...")
        await asyncio.sleep(0.5)
        title_info = await self.get_element_info()
        if title_info:
            # 检测重复
            if self._check_duplicate(title_info, "新闻标题"):
                choice = input("\n选择操作: (r)重新选择 / (c)继续使用 / (d)清除重复项 / (clear)清空所有标识: ").strip().lower()
                if choice == 'r':
                    print("\n3. 请点击新闻标题")
                    input("点击后按 Enter 继续...")
                    await asyncio.sleep(0.5)
                    title_info = await self.get_element_info()
                    if not title_info:
                        return
                elif choice == 'd':
                    # 清除重复项（当前这个）
                    self.clear_element(title_info, "新闻标题")
                elif choice == 'clear':
                    self.clear_selected_elements()
                    return await self.select_news_elements()
            
            method = input("选择定位方式 (tagpath/xpath/text/clear): ").strip().lower() or 'tagpath'
            if method in ['clear', 'clean']:
                # 清除当前选择的内容
                self.clear_element(title_info, "新闻标题")
                # 清除页面高亮
                await self.page.evaluate("removeAllHighlights()")
                # 重新开始选择新闻标题
                print("\n3. 请点击新闻标题")
                input("点击后按 Enter 继续...")
                await asyncio.sleep(0.5)
                # 继续处理，不返回
                title_info = await self.get_element_info()
                if not title_info:
                    return
                # 重新获取定位方式
                method = input("选择定位方式 (tagpath/xpath/text/clear): ").strip().lower() or 'tagpath'
                if method in ['clear', 'clean']:
                    # 如果再次选择clear，递归处理
                    return await self.select_news_elements()
            if method == 'tagpath':
                value = title_info.get('tagpath', title_info.get('xpath', ''))
            elif method == 'xpath':
                value = title_info.get('xpath', '')
            else:
                value = title_info.get('text', '')
            self.config['topic_page']['title'] = {
                'method': method,
                'value': value
            }
            # 注册已选元素
            self._register_element(title_info, "新闻标题")
        
        # 选择发布时间
        print("\n4. 请点击发布时间")
        input("点击后按 Enter 继续...")
        await asyncio.sleep(0.5)
        time_info = await self.get_element_info()
        if time_info:
            # 检测重复
            if self._check_duplicate(time_info, "发布时间"):
                choice = input("\n选择操作: (r)重新选择 / (c)继续使用 / (d)清除重复项 / (clear)清空所有标识: ").strip().lower()
                if choice == 'r':
                    print("\n4. 请点击发布时间")
                    input("点击后按 Enter 继续...")
                    await asyncio.sleep(0.5)
                    time_info = await self.get_element_info()
                    if not time_info:
                        return
                elif choice == 'd':
                    # 清除重复项（当前这个）
                    self.clear_element(time_info, "发布时间")
                elif choice == 'clear':
                    self.clear_selected_elements()
                    return await self.select_news_elements()
            
            method = input("选择定位方式 (tagpath/xpath/text/clear): ").strip().lower() or 'tagpath'
            if method in ['clear', 'clean']:
                # 清除当前选择的内容
                self.clear_element(time_info, "发布时间")
                # 清除页面高亮
                await self.page.evaluate("removeAllHighlights()")
                # 重新开始选择发布时间
                print("\n4. 请点击发布时间")
                input("点击后按 Enter 继续...")
                await asyncio.sleep(0.5)
                # 继续处理，不返回
                time_info = await self.get_element_info()
                if not time_info:
                    return
                # 重新获取定位方式
                method = input("选择定位方式 (tagpath/xpath/text/clear): ").strip().lower() or 'tagpath'
                if method in ['clear', 'clean']:
                    # 如果再次选择clear，递归处理
                    return await self.select_news_elements()
            if method == 'tagpath':
                value = time_info.get('tagpath', time_info.get('xpath', ''))
            elif method == 'xpath':
                value = time_info.get('xpath', '')
            else:
                value = time_info.get('text', '')
            self.config['topic_page']['publish_time'] = {
                'method': method,
                'value': value
            }
            # 注册已选元素
            self._register_element(time_info, "发布时间")
        
        # 选择来源（最多4个）
        self.config['topic_page']['sources'] = []
        for i in range(4):
            print(f"\n5.{i+1} 选择来源 {i+1}")
            print("  请点击来源链接")
            input("  点击后按 Enter 继续...")
            await asyncio.sleep(0.5)
            link_info = await self.get_element_info()
            if not link_info:
                break
            
            # 检测重复
            if self._check_duplicate(link_info, f"来源{i+1}链接"):
                choice = input("  选择操作: (r)重新选择 / (c)继续使用 / (d)清除重复项 / (clear)清空所有标识: ").strip().lower()
                if choice == 'r':
                    # 清除页面高亮
                    await self.page.evaluate("removeAllHighlights()")
                    print(f"\n5.{i+1} 选择来源 {i+1}")
                    print("  请点击来源链接")
                    input("  点击后按 Enter 继续...")
                    await asyncio.sleep(0.5)
                    link_info = await self.get_element_info()
                    if not link_info:
                        break
                elif choice == 'd':
                    # 清除重复项（当前这个）
                    self.clear_element(link_info, f"来源{i+1}链接")
                    # 清除页面高亮
                    await self.page.evaluate("removeAllHighlights()")
                elif choice in ['clear', 'clean']:
                    self.clear_selected_elements()
                    # 清除页面高亮
                    await self.page.evaluate("removeAllHighlights()")
                    return await self.select_news_elements()
            
            method = input("  选择定位方式 (tagpath/xpath/text/clear): ").strip().lower() or 'tagpath'
            if method in ['clear', 'clean']:
                # 清除当前选择的内容
                self.clear_element(link_info, f"来源{i+1}链接")
                # 清除页面高亮
                await self.page.evaluate("removeAllHighlights()")
                # 重新开始选择当前来源
                print(f"\n5.{i+1} 选择来源 {i+1}")
                print("  请点击来源链接")
                input("  点击后按 Enter 继续...")
                await asyncio.sleep(0.5)
                # 继续处理，不跳过
                link_info = await self.get_element_info()
                if not link_info:
                    break
                # 重新获取定位方式
                method = input("  选择定位方式 (tagpath/xpath/text/clear): ").strip().lower() or 'tagpath'
                if method in ['clear', 'clean']:
                    # 如果再次选择clear，继续循环
                    continue
            
            # 获取对应的值
            if method == 'tagpath':
                link_value = link_info.get('tagpath', link_info.get('xpath', ''))
            elif method == 'xpath':
                link_value = link_info.get('xpath', '')
            else:
                link_value = link_info.get('text', '')
            
            source_config = {
                'index': i,
                'link': {
                    'method': method,
                    'value': link_value
                }
            }
            
            # 注册已选元素
            self._register_element(link_info, f"来源{i+1}链接")
            
            # 选择来源名称
            print(f"  请点击来源名称")
            input("  点击后按 Enter 继续...")
            name_info = await self.get_element_info()
            if name_info:
                method = input("  选择定位方式 (tagpath/xpath/text): ").strip().lower() or 'tagpath'
                if method == 'tagpath':
                    name_value = name_info.get('tagpath', name_info.get('xpath', ''))
                elif method == 'xpath':
                    name_value = name_info.get('xpath', '')
                else:
                    name_value = name_info.get('text', '')
                source_config['source_name'] = {
                    'method': method,
                    'value': name_value
                }
            
            # 选择作者
            print(f"  请点击作者")
            input("  点击后按 Enter 继续...")
            author_info = await self.get_element_info()
            if author_info:
                method = input("  选择定位方式 (tagpath/xpath/text): ").strip().lower() or 'tagpath'
                if method == 'tagpath':
                    author_value = author_info.get('tagpath', author_info.get('xpath', ''))
                elif method == 'xpath':
                    author_value = author_info.get('xpath', '')
                else:
                    author_value = author_info.get('text', '')
                source_config['author'] = {
                    'method': method,
                    'value': author_value
                }
            
            # 选择封面图片
            print(f"  请点击封面图片")
            input("  点击后按 Enter 继续...")
            img_info = await self.get_element_info()
            if img_info:
                method = input("  选择定位方式 (tagpath/xpath/text): ").strip().lower() or 'tagpath'
                if method == 'tagpath':
                    img_value = img_info.get('tagpath', img_info.get('xpath', ''))
                elif method == 'xpath':
                    img_value = img_info.get('xpath', '')
                else:
                    img_value = img_info.get('text', '')
                source_config['cover_image'] = {
                    'method': method,
                    'value': img_value
                }
            
            self.config['topic_page']['sources'].append(source_config)
            
            if i < 3:
                continue_more = input(f"\n是否继续选择来源 {i+2}？(y/n): ").strip().lower()
                if continue_more != 'y':
                    break
    
    async def generate_selector_config(self):
        """生成选择器配置"""
        return self.config
    
    def update_config_node(self, element_name: str, method: str, value: str, topic_name: str = None):
        """更新配置文件中对应的节点（只更新该节点，不覆盖其他节点）
        
        Args:
            element_name: 元素名称
            method: 定位方式
            value: 定位值
            topic_name: 主题名称（用于更新列表中的特定主题）
        """
        output_path = "config/selectors.yaml"
        output_file = Path(output_path)
        
        # 读取现有配置（确保保留所有现有配置，包括第三方新闻）
        existing_config = {}
        if output_file.exists():
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    existing_config = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"⚠️ 读取现有配置失败: {e}，将创建新配置")
        
        # 根据元素名称更新对应的节点
        if element_name == "主题链接":
            if 'home_page' not in existing_config:
                existing_config['home_page'] = {}
            
            # 如果提供了主题名称，更新列表中的特定主题
            if topic_name:
                if 'topic_links' not in existing_config['home_page']:
                    existing_config['home_page']['topic_links'] = []
                
                # 查找或创建对应的主题配置
                topic_config = None
                for topic in existing_config['home_page']['topic_links']:
                    if topic.get('name') == topic_name:
                        topic_config = topic
                        break
                
                if not topic_config:
                    topic_config = {'name': topic_name}
                    existing_config['home_page']['topic_links'].append(topic_config)
                
                # 更新主题配置
                topic_config['method'] = method
                topic_config['value'] = value
            else:
                # 兼容旧格式：如果没有提供主题名称，使用单个对象格式
                existing_config['home_page']['topic_links'] = {
                    'method': method,
                    'value': value
                }
        elif element_name == "新闻容器":
            if 'topic_page' not in existing_config:
                existing_config['topic_page'] = {}
            existing_config['topic_page']['news_container'] = {
                'method': method,
                'value': value
            }
        elif element_name.startswith("卡片链接"):
            # 提取索引：卡片链接1 -> index 0
            try:
                index_str = element_name.replace("卡片链接", "").strip()
                index = int(index_str) - 1 if index_str.isdigit() else 0
            except:
                index = 0
            
            if 'topic_page' not in existing_config:
                existing_config['topic_page'] = {}
            if 'sources' not in existing_config['topic_page']:
                existing_config['topic_page']['sources'] = []
            
            # 查找或创建对应的 source 配置
            source_config = None
            for src in existing_config['topic_page']['sources']:
                if src.get('index') == index:
                    source_config = src
                    break
            
            if not source_config:
                source_config = {
                    'index': index,
                    'link': {},
                    'source_name': {'method': '', 'value': ''},
                    'author': {'method': '', 'value': ''},
                    'cover_image': {'method': '', 'value': ''}
                }
                existing_config['topic_page']['sources'].append(source_config)
            
            source_config['link'] = {
                'method': method,
                'value': value
            }
        
        # 保存更新后的配置（保留第三方新闻配置和其他所有配置）
        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, 'w', encoding='utf-8') as f:
                yaml.dump(existing_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            print(f"✓ 配置已更新到: {output_path}")
        except Exception as e:
            print(f"❌ 保存配置失败: {e}")
            import traceback
            traceback.print_exc()
    
    async def save_config(self, config: Dict[str, Any], output_path: str = "config/selectors.yaml"):
        """保存完整配置到文件（用于最终生成配置）"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 读取现有配置并合并
        existing_config = {}
        if output_file.exists():
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    existing_config = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"⚠️ 读取现有配置失败: {e}")
        
        # 合并配置：新配置优先
        def merge_dict(base: Dict, update: Dict) -> Dict:
            """递归合并字典"""
            result = base.copy()
            for key, value in update.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = merge_dict(result[key], value)
                elif key == 'sources' and isinstance(value, list):
                    # 特殊处理 sources 列表：合并索引相同的项
                    if 'sources' not in result:
                        result['sources'] = []
                    existing_sources = {s.get('index'): s for s in result.get('sources', [])}
                    for source in value:
                        idx = source.get('index')
                        if idx is not None and idx in existing_sources:
                            existing_sources[idx] = merge_dict(existing_sources[idx], source)
                        else:
                            existing_sources[idx] = source
                    result['sources'] = list(existing_sources.values())
                else:
                    result[key] = value
            return result
        
        merged_config = merge_dict(existing_config, config)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            yaml.dump(merged_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        
        print(f"\n配置已保存到: {output_path}")
    
    async def validate_config(self, config: Dict[str, Any]) -> bool:
        """验证配置准确性"""
        print("\n=== 验证配置 ===")
        
        try:
            # 验证主题链接
            if 'home_page' in config and 'topic_links' in config['home_page']:
                selector_config = config['home_page']['topic_links']
                method = selector_config['method']
                value = selector_config['value']
                
                if method == 'text':
                    count = await self.page.get_by_text(value).count()
                elif method == 'xpath':
                    count = await self.page.locator(f"xpath={value}").count()
                elif method == 'tagpath':
                    # 使用标签路径定位
                    count = await self.page.evaluate(rf"""
                        () => {{
                            const parts = `{value}`.split('.');
                            let elements = [document];
                            for (let i = 0; i < parts.length; i++) {{
                                const part = parts[i];
                                const match = part.match(/^(\w+)(?:\[(\d+)\])?$/);
                                if (!match) continue;
                                const tagName = match[1];
                                const index = match[2] ? parseInt(match[2]) - 1 : null;
                                const nextElements = [];
                                for (const parent of elements) {{
                                    const children = Array.from(parent.getElementsByTagName(tagName));
                                    if (index !== null) {{
                                        if (children[index]) nextElements.push(children[index]);
                                    }} else {{
                                        nextElements.push(...children);
                                    }}
                                }}
                                elements = nextElements;
                            }}
                            return elements.length;
                        }}
                    """)
                else:
                    count = 0
                
                print(f"主题链接: 找到 {count} 个元素")
            
            # 验证新闻元素
            if 'topic_page' in config:
                topic_config = config['topic_page']
                
                if 'news_item' in topic_config:
                    item_config = topic_config['news_item']
                    method = item_config['method']
                    value = item_config['value']
                    
                    if method == 'xpath':
                        count = await self.page.locator(f"xpath={value}").count()
                    else:
                        count = await self.page.locator(value).count()
                    
                    print(f"新闻项: 找到 {count} 个元素")
            
            print("验证完成")
            return True
        except Exception as e:
            print(f"验证失败: {e}")
            return False
    
    async def cleanup(self):
        """清理资源"""
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
    
    async def run(self):
        """运行工具"""
        try:
            await self.setup_browser()
            await self.inject_selection_script()
            
            print("=== Google News 元素选择工具 ===")
            print("此工具将帮助您选择页面元素并生成定位配置\n")
            
            # 导航到主页
            await self.page.goto(
                "https://news.google.com/home?hl=en-US&gl=US&ceid=US%3Aen",
                wait_until="domcontentloaded"
            )
            print("已打开 Google News 主页")
            await self.handle_google_consent()
            
            # 显示菜单选项
            while True:
                print("\n请选择操作:")
                print("  1. 选择主题链接")
                print("  2. 选择新闻容器")
                print("  3. 选择卡片链接1")
                print("  4. 选择卡片链接2")
                print("  5. 选择卡片链接3")
                print("  6. 选择卡片链接4")
                print("  7. 第三方新闻")
                print("  8. 完成并生成配置")
                choice = input("\n请输入选项 (1-8): ").strip()
                
                if choice == '1':
                    # 等待当前导航完成（如果有的话）
                    try:
                        await self.page.wait_for_load_state("domcontentloaded", timeout=2000)
                    except:
                        pass
                    
                    # 导航到主页（使用 timeout 处理导航冲突）
                    try:
                        await self.page.goto(
                            "https://news.google.com/home?hl=en-US&gl=US&ceid=US%3Aen",
                            wait_until="domcontentloaded",
                            timeout=30000
                        )
                    except Exception as e:
                        # 如果导航被中断，等待页面稳定后重试
                        if "interrupted" in str(e) or "Navigation" in str(e):
                            print("检测到导航冲突，等待页面稳定...")
                            await asyncio.sleep(2)
                            try:
                                await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                            except:
                                pass
                            # 重试导航
                            await self.page.goto(
                                "https://news.google.com/home?hl=en-US&gl=US&ceid=US%3Aen",
                                wait_until="domcontentloaded",
                                timeout=30000
                            )
                        else:
                            raise
                    
                    print("已打开 Google News 主页")
                    await self.handle_google_consent()
                    await self.select_topic_links()
                elif choice == '2':
                    # 选择新闻容器
                    await self.select_news_container()
                elif choice == '3':
                    # 选择卡片链接1
                    await self.select_card_link(1)
                elif choice == '4':
                    # 选择卡片链接2
                    await self.select_card_link(2)
                elif choice == '5':
                    # 选择卡片链接3
                    await self.select_card_link(3)
                elif choice == '6':
                    # 选择卡片链接4
                    await self.select_card_link(4)
                elif choice == '7':
                    # 第三方新闻
                    await self.select_third_party_news()
                elif choice == '8':
                    # 完成并生成配置
                    break
                else:
                    print("无效选项，请重新选择")
            
            # 生成配置
            config = await self.generate_selector_config()
            
            # 验证配置
            await self.validate_config(config)
            
            # 保存配置
            await self.save_config(config)
            
            print("\n工具运行完成！")
            input("按 Enter 关闭浏览器...")
        finally:
            await self.cleanup()


async def main():
    """主函数"""
    helper = SelectorHelper()
    await helper.run()


if __name__ == "__main__":
    asyncio.run(main())

