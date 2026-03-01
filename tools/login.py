"""Google 账号登录工具"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from src.utils.config_loader import load_config, get_crawler_config
from src.utils.browser_config import get_browser_context_options, get_anti_detection_script, get_browser_launch_args


async def login_google(session_file: str = "data/session_state.json"):
    """登录 Google 账号并保存 session"""
    session_path = Path(session_file)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 从 config 读取代理（与主程序一致）；未配置或留空则不走代理
    config = load_config()
    crawler_config = get_crawler_config(config)
    proxy = crawler_config.get("proxy") or None
    if proxy:
        print(f"使用代理: {proxy}")
    else:
        print("未配置代理，直连访问")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=get_browser_launch_args()
        )
        
        context_options = get_browser_context_options(
            storage_state=None,
            proxy=proxy
        )
        context = await browser.new_context(**context_options)
        
        # 移除 webdriver 特征（延迟执行，避免干扰页面交互）
        await context.add_init_script(get_anti_detection_script())
        
        page = await context.new_page()
        
        print("正在打开 Google News...")
        try:
            # 使用更宽松的等待条件，避免超时
            # networkidle 可能因为持续的网络请求而无法达到
            await page.goto(
                "https://news.google.com/home?hl=en-US&gl=US&ceid=US%3Aen",
                wait_until="domcontentloaded",  # 改为 domcontentloaded，更宽松
                timeout=300000  # 增加超时时间到 60 秒
            )
            print("✓ 页面已加载")
        except Exception as e:
            print(f"\n⚠️ 页面加载超时或出错: {e}")
            if "ERR_CONNECTION_CLOSED" in str(e) or "CONNECTION_CLOSED" in str(e):
                print("提示: 连接被关闭通常表示代理未启动或不可用。可在 config/config.yaml 中将 crawler.proxy 设为空或注释掉后重试。")
            print("尝试继续...")
            # 即使超时也继续，让用户手动操作
        
        # 等待页面稳定，确保所有脚本执行完毕
        await asyncio.sleep(3)
        
        print("\n" + "="*60)
        print("浏览器已打开 Google News 页面")
        print("="*60)
        print("\n请手动在浏览器中完成以下操作：")
        print("1. 如果需要登录，请点击页面上的 'Sign in' 按钮")
        print("2. 在登录页面输入您的 Google 账号")
        print("3. 点击 'Next' 或 '下一步' 按钮")
        print("4. 输入密码")
        print("5. 点击 'Next' 或 '下一步' 按钮")
        print("6. 完成所有验证步骤（如需要）")
        print("7. 确保已成功登录到 Google News")
        print("\n如果登录按钮点击无响应，请尝试：")
        print("  - 刷新页面后重试")
        print("  - 检查网络连接")
        print("  - 等待页面完全加载后再点击")
        print("\n登录完成后，请回到此控制台")
        print("="*60)
        print("\n登录完成后，请按 Enter 键继续...")
        input()
        
        # 再次检查登录状态
        try:
            # 等待页面稳定
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(1)
            
            # 检查是否还有登录按钮
            sign_in_button = page.locator("text=Sign in").first
            sign_in_count = await sign_in_button.count() if sign_in_button else 0
            
            if sign_in_count > 0:
                print("\n⚠️ 警告: 仍然检测到登录按钮，可能登录未完成")
                print("请确保已成功登录，然后按 Enter 继续...")
                input()
            else:
                print("\n✓ 登录状态检查通过")
        except Exception as e:
            print(f"\n登录状态检查时出现异常: {e}")
            print("请手动确认已登录，然后按 Enter 继续...")
            input()
        
        # 保存 session 状态
        await context.storage_state(path=session_file)
        print(f"\nSession 已保存到: {session_file}")
        
        await browser.close()
        print("登录完成！")


def check_login_status(session_file: str = "data/session_state.json") -> bool:
    """检查 session 文件是否存在"""
    return Path(session_file).exists()


async def main():
    """主函数"""
    session_file = "data/session_state.json"
    
    if check_login_status(session_file):
        print(f"检测到已存在的 session 文件: {session_file}")
        response = input("是否重新登录？(y/n): ")
        if response.lower() != 'y':
            print("取消登录")
            return
    
    await login_google(session_file)


if __name__ == "__main__":
    asyncio.run(main())

