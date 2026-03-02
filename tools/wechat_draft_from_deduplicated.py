"""
读取 news-standard/当前日期/news_deduplicated.json，将 items 转为 Markdown，
再通过 tools/markdown_to_html.py 转换为 HTML，调用微信公众号「新增草稿」接口发送到草稿箱。

可选：使用豆包大模型将 Markdown 整理成符合微信公众号图文风格后再转 HTML（use_doubao_format=True）。
API 文档：
- 获取凭据: https://developers.weixin.qq.com/doc/subscription/api/base/api_getaccesstoken.html
- 新增草稿: https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 使用 tools/markdown_to_html 做 Markdown -> HTML 转换
sys.path.insert(0, str(Path(__file__).resolve().parent))
from markdown_to_html import markdown_to_html_body

NEWS_STANDARD_DIR = PROJECT_ROOT / "news-standard"

# 豆包（火山方舟）用于「微信公众号风格」改写
ARK_API_BASE = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
ARK_MODEL_ID = "doubao-seed-1-6-lite-251015"
WECHAT_FORMAT_PROMPT = """你是微信公众号编辑。下面是要闻汇总，请完成两件事：
1. 总结新闻（只总结，不要存在多余输出）并挑选你认为每个领域最重要的前10条新闻。
2. 将总结后的新闻转为可直接填入公众号 content 的 HTML。

规则要求：
- 只使用微信公众号支持的标签：p、h1~h6、strong、em、u、br、hr、ul、ol、li。
- 不使用：html、head、body、style、class、id、script、iframe 等会被过滤的标签。
- 所有样式必须用行内 style，不写头部样式。
- 内容严肃、正式、客观，为国际要闻汇总。
- 仅输出可直接填入公众号接口 content 字段的 HTML 字符串，不输出多余文字、解释、说明或分隔符。

新闻：
---
{plain_text}
---"""


def load_config():
    from src.utils.config_loader import load_config as _load
    return _load()


def get_wechat_config(config):
    return config.get("wechat", {})


def get_access_token(app_id: str, app_secret: str, api_base_url: str) -> str:
    """获取 access_token。"""
    import urllib.request
    url = f"{api_base_url.rstrip('/')}/cgi-bin/token"
    params = f"grant_type=client_credential&appid={app_id}&secret={app_secret}"
    req = urllib.request.Request(f"{url}?{params}", method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "access_token" not in data:
        raise RuntimeError(data.get("errmsg", "获取 access_token 失败"))
    return data["access_token"]


def draft_add(access_token: str, api_base_url: str, articles: list) -> dict:
    """新增草稿。articles 为微信 articles 格式列表。"""
    import urllib.request
    url = f"{api_base_url.rstrip('/')}/cgi-bin/draft/add?access_token={access_token}"
    body = json.dumps({"articles": articles}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    if "errcode" in out and out["errcode"] != 0:
        raise RuntimeError(f"草稿接口错误: {out.get('errmsg', out)}")
    return out


# 分类展示顺序（未在此列表中的归入「其他」并排在最后）
_CATEGORY_ORDER = [
    "政治", "经济", "军事", "国际", "法制", "社会", "教育", "文化",
    "科技", "农业", "卫生健康", "娱乐", "体育", "其他",
]


def items_to_markdown(items: list) -> str:
    """将 news_deduplicated 的 items 按 category 分类，按 _CATEGORY_ORDER 顺序组装，构造与 minimal/tech 主题对应的 Markdown。"""
    by_category = {}
    for item in items:
        cat = (item.get("category") or "").strip() or "其他"
        if cat not in _CATEGORY_ORDER:
            cat = "其他"
        by_category.setdefault(cat, []).append(item)
    lines = []
    for idx, cat in enumerate(_CATEGORY_ORDER):
        group = by_category.get(cat, [])
        if not group:
            continue
        if idx > 0:
            lines.append("")
            lines.append("---")
            lines.append("")
        lines.append(f"## {cat}")
        lines.append("")
        for i, item in enumerate(group, 1):
            summary = (item.get("summary") or "").strip() or "无摘要"
            domain = (item.get("domain") or "").strip()
            lines.append(f"- **{i}. {summary}**")
            if domain:
                lines.append(f"  来源：{domain}")
            lines.append("")
    return "\n".join(lines).strip()


def items_to_plain_text(items: list) -> str:
    """将 news_deduplicated 的 items 按 category 分类，按 _CATEGORY_ORDER 顺序组装为带编号的纯文本（无 Markdown 符号）。"""
    by_category = {}
    for item in items:
        cat = (item.get("category") or "").strip() or "其他"
        if cat not in _CATEGORY_ORDER:
            cat = "其他"
        by_category.setdefault(cat, []).append(item)
    lines = []
    for idx, cat in enumerate(_CATEGORY_ORDER):
        group = by_category.get(cat, [])
        if not group:
            continue
        if idx > 0:
            lines.append("")
        lines.append(cat)
        lines.append("")
        for i, item in enumerate(group, 1):
            summary = (item.get("summary") or "").strip() or "无摘要"
            domain = (item.get("domain") or "").strip()
            lines.append(f"{i}. {summary}")
            if domain:
                lines.append(f"来源：{domain}")
            lines.append("")
    return "\n".join(lines).strip()


def _call_doubao_wechat_format(plain_text: str, api_key: str) -> str:
    """调用豆包将带编号的纯文本整理成符合微信公众号风格的 HTML 片段，返回可直接用作草稿 content 的 HTML。"""
    import urllib.request
    safe_text = (plain_text or "").replace("{", "{{").replace("}", "}}")
    user_content = WECHAT_FORMAT_PROMPT.format(plain_text=safe_text)
    body = {
        "model": ARK_MODEL_ID,
        "messages": [{"role": "user", "content": user_content}],
        "stream": False,
        "thinking": {"type": "disabled"},
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
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
    out = json.loads(raw)
    if out.get("error"):
        raise RuntimeError(out["error"].get("message", str(out["error"])))
    choices = out.get("choices") or []
    if not choices:
        raise RuntimeError("豆包 API 返回无 choices")
    return (choices[0].get("message") or {}).get("content") or ""


def build_single_article(
    items: list,
    default_thumb_media_id: str,
    title: str = "今日要闻汇总",
    use_doubao_format: bool = False,
    doubao_api_key: Optional[str] = None,
) -> dict:
    """将 news_deduplicated 全部条目转为 Markdown，再经 markdown_to_html 转为 HTML 后作为图文草稿正文。

    use_doubao_format: 为 True 时，先调用豆包大模型将 Markdown 整理成符合微信公众号风格，再转 HTML。
    doubao_api_key: 豆包 API Key，不传则使用 config 中 doubao.api_key。
    """
    title = (title or "今日要闻")[:32]
    if use_doubao_format:
        api_key = (doubao_api_key or "").strip() or (load_config().get("doubao") or {}).get("api_key") or ""
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError("使用豆包改写时需在 config 中配置 doubao.api_key")
        plain_text = items_to_plain_text(items)
        content = _call_doubao_wechat_format(plain_text, api_key)
    else:
        md = items_to_markdown(items)
        content = markdown_to_html_body(md)
    return {
        "article_type": "news",
        "title": title,
        "author": "meolord",
        "digest": title,
        "content": content,
        "content_source_url": "",
        "thumb_media_id": default_thumb_media_id,
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }


def main():
    config = load_config()
    wechat = get_wechat_config(config)
    app_id = wechat.get("app_id", "").strip()
    app_secret = wechat.get("app_secret", "").strip()
    api_base_url = (wechat.get("api_base_url") or "https://api.weixin.qq.com").strip()
    draft_cfg = wechat.get("draft") or {}
    default_thumb_media_id = (draft_cfg.get("default_thumb_media_id") or "").strip()

    if not app_id or not app_secret:
        print("请在 config/config.yaml 的 wechat 中配置 app_id 与 app_secret（或环境变量 WECHAT_APP_ID / WECHAT_APP_SECRET）")
        return
    if not default_thumb_media_id:
        print("请在 config/config.yaml 的 wechat.draft 中配置 default_thumb_media_id（永久素材封面图 ID）")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    dedup_path = NEWS_STANDARD_DIR / today / "news_deduplicated.json"
    if not dedup_path.is_file():
        print(f"文件不存在: {dedup_path}")
        return

    items = json.loads(dedup_path.read_text(encoding="utf-8"))
    if not items:
        print("news_deduplicated.json 为空，无需推送草稿")
        return

    use_doubao_format = bool(draft_cfg.get("use_doubao_format", False))
    doubao_api_key = ((config.get("doubao") or {}).get("api_key") or "").strip()

    access_token = get_access_token(app_id, app_secret, api_base_url)
    one_article = build_single_article(
        items,
        default_thumb_media_id,
        title=f"今日要闻 {today}",
        use_doubao_format=use_doubao_format,
        doubao_api_key=doubao_api_key or None,
    )
    result = draft_add(access_token, api_base_url, [one_article])
    media_id = result.get("media_id")
    if media_id:
        print(f"已生成一篇草稿，共整合 {len(items)} 条，media_id={media_id}" + ("（已用豆包整理为公众号风格）" if use_doubao_format else ""))
    else:
        print("草稿接口未返回 media_id")


if __name__ == "__main__":
    main()
