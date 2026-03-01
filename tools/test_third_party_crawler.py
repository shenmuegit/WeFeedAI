"""测试第三方新闻爬取脚本"""
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright
from urllib.parse import urlparse

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config_loader import load_selectors
from src.utils.browser_config import get_browser_context_options, get_anti_detection_script, get_browser_launch_args


async def extract_third_party_news(url: str, domain: str, selectors: dict):
    """提取第三方新闻内容"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # 设置为 False 以便查看浏览器
            args=get_browser_launch_args()
        )
        
        context_options = get_browser_context_options()
        context = await browser.new_context(**context_options)
        
        # 移除 webdriver 特征
        await context.add_init_script(get_anti_detection_script())
        
        page = await context.new_page()
        
        try:
            print(f"\n正在访问: {url}")
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(2)  # 等待页面加载
            
            # 获取域名配置
            domain_config = selectors.get('third_party_news', {}).get(domain, {})
            
            if not domain_config:
                print(f"❌ 未找到域名 {domain} 的配置")
                return None
            
            result = {
                'url': url,
                'domain': domain,
                'title': None,
                'content': None,
                'cover': None,
                'author': None
            }
            
            # 提取标题
            title_config = domain_config.get('title', {})
            if title_config.get('method') and title_config.get('value'):
                try:
                    title_locator = page.locator(f"xpath={title_config['value']}")
                    if await title_locator.count() > 0:
                        result['title'] = await title_locator.text_content()
                        print(f"\n✓ 标题: {result['title']}")
                    else:
                        print(f"\n⚠️ 未找到标题元素")
                except Exception as e:
                    print(f"\n❌ 提取标题失败: {e}")
            
            # 提取内容
            content_config = domain_config.get('content', {})
            if content_config.get('method') and content_config.get('value'):
                try:
                    content_locator = page.locator(f"xpath={content_config['value']}")
                    if await content_locator.count() > 0:
                        result['content'] = await content_locator.text_content()
                        print(f"\n✓ 内容 (前200字符): {result['content'][:200] if result['content'] else 'None'}...")
                    else:
                        print(f"\n⚠️ 未找到内容元素")
                except Exception as e:
                    print(f"\n❌ 提取内容失败: {e}")
            
            # 提取封面图片
            cover_config = domain_config.get('cover', {})
            if cover_config.get('method') and cover_config.get('value'):
                try:
                    cover_locator = page.locator(f"xpath={cover_config['value']}")
                    if await cover_locator.count() > 0:
                        # 检查是否是 img 标签
                        tag_name = await cover_locator.evaluate("el => el.tagName.toLowerCase()")
                        
                        if tag_name == 'img':
                            # 获取 img 的 src 属性
                            result['cover'] = await cover_locator.get_attribute('src')
                            print(f"\n✓ 封面图片 (img src): {result['cover']}")
                        elif tag_name == 'source':
                            # 获取 source 的 srcset 属性
                            result['cover'] = await cover_locator.get_attribute('srcset')
                            print(f"\n✓ 封面图片 (source srcset): {result['cover']}")
                        else:
                            # 尝试在子元素中查找 img 或 source
                            img_locator = cover_locator.locator('img').first
                            source_locator = cover_locator.locator('source').first
                            
                            if await img_locator.count() > 0:
                                result['cover'] = await img_locator.get_attribute('src')
                                print(f"\n✓ 封面图片 (子元素 img src): {result['cover']}")
                            elif await source_locator.count() > 0:
                                result['cover'] = await source_locator.get_attribute('srcset')
                                print(f"\n✓ 封面图片 (子元素 source srcset): {result['cover']}")
                            else:
                                print(f"\n⚠️ 未找到封面图片 (img 或 source)")
                    else:
                        print(f"\n⚠️ 未找到封面元素")
                except Exception as e:
                    print(f"\n❌ 提取封面失败: {e}")
            
            # 提取作者
            author_config = domain_config.get('author', {})
            if author_config.get('method') and author_config.get('value'):
                try:
                    author_locator = page.locator(f"xpath={author_config['value']}")
                    if await author_locator.count() > 0:
                        result['author'] = await author_locator.text_content()
                        print(f"\n✓ 作者: {result['author']}")
                    else:
                        print(f"\n⚠️ 未找到作者元素")
                except Exception as e:
                    print(f"\n❌ 提取作者失败: {e}")
            
            # 等待用户查看（可选）
            print(f"\n{'='*60}")
            print("提取完成！浏览器将保持打开状态 10 秒供查看...")
            print(f"{'='*60}")
            await asyncio.sleep(10)
            
            return result
            
        except Exception as e:
            print(f"\n❌ 爬取失败: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            await browser.close()


def extract_domain_from_url(url: str) -> str:
    """从 URL 中提取域名"""
    parsed = urlparse(url)
    domain = parsed.netloc
    # 移除 www. 前缀
    if domain.startswith('www.'):
        domain = domain[4:]
    return domain


async def main():
    """主函数"""
    url = "https://www.theguardian.com/us-news/live/2026/feb/02/donald-trump-jeffrey-epstein-files-trevor-noah-ice-minnesota-minneapolis-cuba-latest-news-updates"
    domain = extract_domain_from_url(url)
    
    print(f"测试第三方新闻爬取")
    print(f"URL: {url}")
    print(f"域名: {domain}")
    
    # 加载选择器配置
    try:
        selectors = load_selectors("config/selectors.yaml")
        print(f"\n✓ 配置加载成功")
    except Exception as e:
        print(f"\n❌ 加载配置失败: {e}")
        return
    
    # 提取内容
    result = await extract_third_party_news(url, domain, selectors)
    
    # 输出结果摘要
    if result:
        print(f"\n{'='*60}")
        print("提取结果摘要:")
        print(f"{'='*60}")
        print(f"标题: {result['title']}")
        print(f"内容长度: {len(result['content']) if result['content'] else 0} 字符")
        print(f"封面图片: {result['cover']}")
        print(f"作者: {result['author']}")
        print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())

