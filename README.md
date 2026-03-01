# WeFeedAI

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/yourusername/WeFeedAI)
[![Python](https://img.shields.io/badge/python-3.8+-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

自动爬取 Google News，通过 AI 精炼内容，并发布到微信公众号的开源项目。

## 📋 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [安装](#安装)
- [使用](#使用)
- [配置说明](#配置说明)
- [版本历史](#版本历史)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

## ✨ 功能特性

- 🔍 **智能爬取**：自动爬取 Google News 头条和订阅主题新闻
- 🤖 **AI 精炼**：使用 DeepSeek AI 精炼和整合多来源新闻内容
- 📊 **相关性分析**：分析新闻相关性，生成多维度标签
- 📝 **自动发布**：自动生成微信文章并发布到公众号
- ⏰ **定时任务**：支持 Cron 表达式配置定时执行
- 🔄 **智能去重**：按天去重，避免重复处理相同内容
- 🎯 **可视化配置**：提供可视化工具配置页面元素选择器

## 🛠 技术栈

- **Python 3.8+**
- **Playwright** - 浏览器自动化
- **DeepSeek API** - AI 内容处理
- **APScheduler** - 定时任务调度
- **PyYAML** - 配置文件解析
- **BeautifulSoup4** - HTML 解析

## 📁 项目结构

```
WeFeedAI/
├── config/                  # 配置文件
│   ├── config.yaml         # 主配置文件
│   └── selectors.yaml      # 页面元素定位配置（自动生成）
├── tools/                   # 辅助工具
│   ├── login.py            # Google 账号登录工具
│   └── selector_helper.py  # 可视化元素选择器工具
├── src/                     # 源代码
│   ├── crawler/            # 爬取模块
│   │   ├── google_news.py  # Google News 爬取
│   │   └── article_detail.py # 文章详情爬取
│   ├── ai/                 # AI 处理模块
│   │   ├── deepseek_client.py    # DeepSeek API 客户端
│   │   └── content_processor.py  # 内容处理
│   ├── wechat/             # 微信 API 模块
│   │   ├── auth.py         # 微信认证
│   │   ├── draft.py        # 草稿管理
│   │   └── publish.py      # 文章发布
│   ├── utils/              # 工具模块
│   │   ├── browser_config.py  # 浏览器配置
│   │   ├── config_loader.py   # 配置加载
│   │   ├── deduplicator.py    # 去重逻辑
│   │   └── logger.py          # 日志工具
│   └── main.py             # 主程序入口
├── data/                    # 数据存储
│   ├── articles_*.json     # 爬取的新闻数据
│   ├── refined_*.json      # AI 精炼后的内容
│   ├── relationships_*.json # 相关性分析数据
│   ├── processed_*.json    # 已处理文章记录
│   └── session_state.json  # 浏览器会话状态
├── logs/                    # 日志文件
├── requirements.txt         # Python 依赖
├── .env.example            # 环境变量模板
└── README.md               # 项目说明
```

## 🚀 安装

### 前置要求

- Python 3.8 或更高版本
- 已安装 Git

### 安装步骤

1. **克隆项目**
```bash
git clone https://github.com/yourusername/WeFeedAI.git
cd WeFeedAI
```

2. **创建虚拟环境（推荐）**
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

3. **安装依赖**
```bash
pip install -r requirements.txt
playwright install chromium
```

4. **配置环境变量**
```bash
cp .env.example .env
# 编辑 .env 文件，填入以下配置：
# - DEEPSEEK_API_KEY=your_deepseek_api_key
# - WECHAT_APP_ID=your_wechat_app_id
# - WECHAT_APP_SECRET=your_wechat_app_secret
```

5. **配置主配置文件**
```bash
# 编辑 config/config.yaml，配置爬取、AI、微信等参数
```

## 📖 使用

### 首次设置

#### 1. 登录 Google 账号

运行登录工具，在浏览器中手动登录 Google 账号：

```bash
python tools/login.py
```

登录成功后，session 会自动保存到 `data/session_state.json`，后续运行无需重复登录。

#### 2. 配置页面元素选择器

使用可视化工具选择页面元素，生成选择器配置：

```bash
python tools/selector_helper.py
```

按照提示在浏览器中选择以下元素：
- 主题链接
- 新闻容器
- 新闻卡片
- 卡片链接（最多4个）

配置会自动保存到 `config/selectors.yaml`。

### 运行程序

#### 手动运行

```bash
python src/main.py
```

#### 定时任务

程序会根据 `config/config.yaml` 中的 `scheduler.cron` 配置自动执行。

示例配置：
```yaml
scheduler:
  enabled: true
  cron: "0 8 * * *"  # 每天上午 8 点执行
```

## ⚙️ 配置说明

### config/config.yaml

主配置文件，包含以下配置项：

- **crawler**: 爬取配置
  - `google_news_url`: Google News URL
  - `thread_pool_size`: 线程池大小
  - `request_delay`: 请求延迟（秒）
  - `proxy`: 代理地址（可选）
  
- **ai**: AI 配置
  - `api_key`: DeepSeek API Key（从环境变量读取）
  - `model`: 使用的模型
  - `temperature`: 温度参数
  - `max_tokens`: 最大 token 数
  
- **wechat**: 微信配置
  - `app_id`: 微信 AppID（从环境变量读取）
  - `app_secret`: 微信 AppSecret（从环境变量读取）
  
- **scheduler**: 定时任务配置
  - `enabled`: 是否启用定时任务
  - `cron`: Cron 表达式
  
- **logging**: 日志配置
  - `level`: 日志级别
  - `file`: 日志文件路径
  - `format`: 日志格式

### config/selectors.yaml

页面元素定位配置文件，由 `tools/selector_helper.py` 自动生成。

每个选择器包含：
- `method`: 定位方法（tagpath/xpath/text）
- `value`: 定位值

## 📝 版本历史

### [1.0.0] - 2026-02-01

#### 新增
- 初始版本发布
- Google News 爬取功能
- DeepSeek AI 内容精炼
- 微信文章自动发布
- 可视化元素选择器工具
- 定时任务支持
- 按天去重功能

#### 技术特性
- 支持 Playwright 浏览器自动化
- 支持代理配置
- 支持多线程并发处理
- 支持会话持久化

## 🤝 贡献指南

欢迎所有形式的贡献！

### 如何贡献

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 代码规范

- 遵循 PEP 8 Python 代码规范
- 使用有意义的变量和函数名
- 添加必要的注释和文档字符串
- 确保代码通过 lint 检查

### 报告问题

如发现问题，请在 [Issues](https://github.com/yourusername/WeFeedAI/issues) 页面提交，包含：
- 问题描述
- 复现步骤
- 预期行为
- 实际行为
- 环境信息（Python 版本、操作系统等）

## ⚠️ 注意事项

- 确保已安装 Playwright 浏览器（运行 `playwright install chromium`）
- 首次使用需要手动登录 Google 账号
- 需要配置 DeepSeek API Key 和微信 AppID/AppSecret
- 建议在 Linux 服务器上运行以获得更好的稳定性
- 使用代理时，确保代理地址正确且可访问
- 遵守 Google News 和微信公众号的使用条款

## 📄 许可证

本项目采用 MIT 许可证。详情请参阅 [LICENSE](LICENSE) 文件。

## 🙏 致谢

- [Playwright](https://playwright.dev/) - 强大的浏览器自动化工具
- [DeepSeek](https://www.deepseek.com/) - AI 内容处理服务
- [APScheduler](https://apscheduler.readthedocs.io/) - Python 定时任务库

## 📮 联系方式

- 项目主页: https://github.com/yourusername/WeFeedAI
- 问题反馈: https://github.com/yourusername/WeFeedAI/issues
- 讨论区: https://github.com/yourusername/WeFeedAI/discussions

---

**⭐ 如果这个项目对你有帮助，请给个 Star！**
