"""
读取 news/当天日期/ 下所有 JSON 的 content，调用豆包大模型做摘要与分类，
将结果按分类写入 news-standard/当天日期/分类名/ 下。

豆包 API 文档: https://www.volcengine.com/docs/82379/1399009?lang=zh
模型 ID: doubao-seed-1-6-lite-251015
API Key: config/config.yaml 中 doubao.api_key
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load_config():
    from src.utils.config_loader import load_config
    return load_config()

NEWS_DIR = PROJECT_ROOT / "news"
NEWS_STANDARD_DIR = PROJECT_ROOT / "news-standard"

# 豆包 API（火山方舟）
ARK_API_BASE = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
MODEL_ID = "doubao-seed-1-6-lite-251015"

# 分类列表（与提示词一致）
CATEGORIES = [
    "政治", "经济", "军事", "国际", "社会", "科技", "文化", "教育",
    "体育", "娱乐", "法制", "卫生健康", "农业",
]

# 模板中示例 JSON 的花括号用 {{ }} 转义，仅 {content} 为占位符，否则 .format() 会报错
PROMPT_TEMPLATE = """用一句话精炼总结新闻核心内容；
从政治、经济、军事、国际、社会、科技、文化、教育、体育、娱乐、法制、卫生健康、农业中选唯一最贴合类别；
输出格式：
{{
"summary": "一句话总结",
"category": "新闻分类"
}}

新闻正文：
---
{content}
---
请只输出上述 JSON，不要其他内容。"""


def get_ark_api_key() -> str:
    """从 config doubao.api_key 读取"""
    config = _load_config()
    key = (config.get("doubao") or {}).get("api_key") or ""
    return (key or "").strip()


def call_doubao(content: str, api_key: str) -> str:
    """调用豆包文本生成 API，返回助手回复文本"""
    import urllib.request

    # 转义 content 中的花括号，避免被 .format() 当作占位符（如 JSON 片段导致报错）
    safe_content = content.replace("{", "{{").replace("}", "}}")
    user_content = PROMPT_TEMPLATE.format(content=safe_content)
    body = {
        "model": MODEL_ID,
        "messages": [
            {"role": "user", "content": user_content},
        ],
        "stream": False,
		"thinking":{
			"type":"disabled"
		}
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ARK_API_BASE,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = resp.read().decode("utf-8")
    try:
        out = json.loads(raw)
    except json.JSONDecodeError as e:
        # 若为 SSE 流式响应，取第一行 data: 后的 JSON
        if raw.strip().startswith("data:"):
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        out = json.loads(line[6:].strip())
                        break
                    except json.JSONDecodeError:
                        continue
            else:
                raise RuntimeError(f"API 返回流式数据但解析失败: {e}") from e
        else:
            raise RuntimeError(f"API 返回非 JSON (前 300 字): {raw[:300]}") from e
    if "error" in out:
        raise RuntimeError(out["error"].get("message", str(out["error"])))
    choices = out.get("choices") or []
    if not choices:
        raise RuntimeError("API 返回无 choices")
    return (choices[0].get("message") or {}).get("content") or ""


def parse_summary_category(text: str) -> tuple:
    """从模型输出中解析 summary 和 category，失败返回 (None, None)"""
    text = (text or "").strip()
    # 尝试提取 JSON 块
    m = re.search(r"\{[^{}]*\"summary\"[^{}]*\"category\"[^{}]*\}", text, re.DOTALL)
    if not m:
        m = re.search(r"\{[\s\S]*?\}", text)
    if not m:
        return None, None
    try:
        obj = json.loads(m.group())
        summary = obj.get("summary") or obj.get("summary_zh")
        category = (obj.get("category") or "").strip()
        if category not in CATEGORIES:
            # 映射常见别称或去掉空格
            for c in CATEGORIES:
                if c in category or category in c:
                    category = c
                    break
            else:
                category = "社会"  # 默认
        return (summary or "").strip(), category
    except json.JSONDecodeError:
        return None, None


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    news_date_dir = NEWS_DIR / today
    if not news_date_dir.is_dir():
        print(f"目录不存在: {news_date_dir}")
        return

    api_key = get_ark_api_key()

    # 输出根目录：news-standard/当天/
    standard_date_dir = NEWS_STANDARD_DIR / today
    standard_date_dir.mkdir(parents=True, exist_ok=True)
    for cat in CATEGORIES:
        (standard_date_dir / cat).mkdir(parents=True, exist_ok=True)

    json_files = list(news_date_dir.glob("*.json"))
    if not json_files:
        print(f"未找到 JSON 文件: {news_date_dir}")
        return

    print(f"共 {len(json_files)} 个 JSON，开始调用豆包并分类写入 {standard_date_dir}")

    for i, path in enumerate(json_files, 1):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [{i}/{len(json_files)}] 读取失败 {path.name}: {e}")
            continue

        content = (raw.get("content") or "").strip()
        if not content:
            print(f"  [{i}/{len(json_files)}] 跳过无 content: {path.name}")
            continue

        try:
            reply = call_doubao(content, api_key)
        except Exception as e:
            print(f"  [{i}/{len(json_files)}] API 失败 {path.name}: {e}")
            continue

        summary, category = parse_summary_category(reply)
        if summary is None and category is None:
            print(f"  [{i}/{len(json_files)}] 解析失败 {path.name}, reply: {reply[:200]}...")
            summary = ""
            category = "社会"

        # 写入到 news-standard/当天/分类/ 下，文件名与原 JSON 一致
        out_obj = {
            "url": raw.get("url"),
            "title": raw.get("title"),
            "summary": summary,
            "category": category,
            "content": content[:500] + "…" if len(content) > 500 else content,
            "topic": raw.get("topic"),
            "crawled_at": raw.get("crawled_at"),
            "source_file": path.name,
        }
        out_dir = standard_date_dir / category
        out_path = out_dir / path.name
        out_path.write_text(json.dumps(out_obj, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [{i}/{len(json_files)}] {path.name} -> {category}/")

    print("完成。")


if __name__ == "__main__":
    main()
