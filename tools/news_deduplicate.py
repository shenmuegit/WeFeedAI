"""
读取 news-standard/当前日期/ 下各分类目录中的 JSON，调用豆包大模型做重复检测，
只保留每组重复中的第一条及未重复项，写入同目录下的 news_deduplicated.json。

API Key: config/config.yaml 中 doubao.api_key
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load_config():
    from src.utils.config_loader import load_config
    return load_config()

NEWS_STANDARD_DIR = PROJECT_ROOT / "news-standard"
ARK_API_BASE = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
MODEL_ID = "doubao-seed-1-6-lite-251015"

DEDUP_PROMPT_TEMPLATE = """新闻重复内容检测提示词
你是专业的新闻内容去重检测专家，严格按照以下规则执行任务：
任务规则
我会输入带编号的新闻列表，每条新闻以「数字编号 + 内容」形式呈现。
你只需要识别高度重复的新闻，将它们的编号分组。
输出格式要求：
每组重复新闻的编号占一行
同一组内编号用英文逗号分隔
只输出编号组，不输出任何多余文字、解释、标题
无重复则输出：无重复

以下为待检测的新闻列表（编号 内容）：
{numbered_list}"""


def parse_domain_from_url(url: str) -> str:
    """从 URL 解析域名，去掉 www. 前缀。"""
    if not url or not isinstance(url, str):
        return ""
    try:
        parsed = urlparse(url)
        domain = (parsed.netloc or parsed.path or "").strip()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def get_ark_api_key() -> str:
    config = _load_config()
    key = (config.get("doubao") or {}).get("api_key") or ""
    return (key or "").strip()


def call_doubao(user_content: str, api_key: str) -> str:
    """调用豆包 API，发送一段用户内容，返回助手回复文本。"""
    import urllib.request
    body = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": user_content}],
        "stream": False,
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
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
    out = json.loads(raw)
    if "error" in out:
        raise RuntimeError(out["error"].get("message", str(out["error"])))
    choices = out.get("choices") or []
    if not choices:
        raise RuntimeError("API 返回无 choices")
    return (choices[0].get("message") or {}).get("content") or ""


def parse_dedup_response(reply: str, max_index: int) -> set:
    """解析去重 API 返回的编号组，返回应保留的编号集合。"""
    keep_indices = set()
    reply = (reply or "").strip()
    if "无重复" in reply and "," not in reply:
        return set(range(1, max_index + 1))
    duplicate_groups = []
    for line in reply.splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        parts = [p.strip() for p in line.split(",") if p.strip()]
        numbers = []
        for p in parts:
            try:
                n = int(p)
                if 1 <= n <= max_index:
                    numbers.append(n)
            except ValueError:
                continue
        if len(numbers) >= 2:
            duplicate_groups.append(numbers)
    in_any_group = set()
    for group in duplicate_groups:
        for n in group:
            in_any_group.add(n)
        keep_indices.add(group[0])
    for i in range(1, max_index + 1):
        if i not in in_any_group:
            keep_indices.add(i)
    return keep_indices if keep_indices else set(range(1, max_index + 1))


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    date_dir = NEWS_STANDARD_DIR / today
    if not date_dir.is_dir():
        print(f"目录不存在: {date_dir}")
        return

    # 读取当前日期下所有分类子目录中的 JSON（排除 news_deduplicated.json）
    collected = []
    for path in sorted(date_dir.glob("*/*.json")):
        if path.name == "news_deduplicated.json":
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  跳过 {path}: {e}")
            continue
        url = obj.get("url") or ""
        obj["domain"] = parse_domain_from_url(url)
        summary = (obj.get("summary") or "").strip()
        collected.append({"index": len(collected) + 1, "summary": summary, "url": url, "domain": obj["domain"], "out_obj": obj})

    if not collected:
        print(f"未找到 JSON 文件: {date_dir}/*/*.json")
        return

    print(f"共读取 {len(collected)} 条，调用豆包去重...")
    api_key = get_ark_api_key()
    numbered_list = "\n".join(f"{item['index']} {item['summary']}" for item in collected)
    dedup_content = DEDUP_PROMPT_TEMPLATE.format(numbered_list=numbered_list)
    dedup_reply = call_doubao(dedup_content, api_key)
    keep_indices = parse_dedup_response(dedup_reply, len(collected))
    filtered = [collected[i - 1]["out_obj"] for i in sorted(keep_indices) if 1 <= i <= len(collected)]
    out_path = date_dir / "news_deduplicated.json"
    out_path.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"去重完成：保留 {len(filtered)} 条（共 {len(collected)} 条），已写入 {out_path}")


if __name__ == "__main__":
    main()
