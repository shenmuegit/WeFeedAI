"""临时脚本：从 missing_domains.txt 提取第一列追加到 selectors.yaml，第二列（URL）写入本地文件"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SELECTORS_PATH = PROJECT_ROOT / "config" / "selectors.yaml"
MISSING_PATH = PROJECT_ROOT / "config" / "missing_domains.txt"
URLS_OUTPUT_PATH = PROJECT_ROOT / "config" / "missing_domains_urls.txt"

# 已存在于 selectors 的 third_party_news 域名（从 grep 结果整理）
EXISTING = set("""
theguardian.com axios.com edition.cnn.com bbc.com wsbtv.com yahoo.com
cbsnews.com lohud.com nytimes.com hollywoodreporter.com npr.org aljazeera.com
eu.usatoday.com gzeromedia.com gamesradar.com reuters.com france24.com cpr.org
whitehouse.gov wsj.com thehill.com politico.com virginiamercury.com barrons.com
abc7.com ktla.com startribune.com ms.now foxnews.com gothamist.com
federalnewsnetwork.com twz.com ndtv.com dropsitenews.com dw.com sudanspost.com
cbc.ca euronews.com oilprice.com news.err.ee techpolicy.press osvnews.com
haaretz.com lemonde.fr english.kyodonews.net nbcnews.com apnews.com
miamiherald.com pbs.org usatoday.com cnbc.com freep.com clickondetroit.com
abcnews.com timesofisrael.com knsiradio.com kstp.com fox9.com democracydocket.com
katu.com wivb.com cityandstateny.com motherjones.com
""".split())

def main():
    text = MISSING_PATH.read_text(encoding="utf-8")
    unique = []
    urls = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) >= 2:
            d = parts[0].strip()
            url = parts[1].strip()
            if url:
                urls.append(url)
            if d and d != "chromewebdata" and d not in EXISTING and d not in seen:
                seen.add(d)
                unique.append(d)

    # 抽取第二列链接到本地文件
    if urls:
        URLS_OUTPUT_PATH.write_text("\n".join(urls) + "\n", encoding="utf-8")
        print(f"已抽取 {len(urls)} 个链接到 {URLS_OUTPUT_PATH}")
    else:
        print("未找到有效链接，未写入 URL 文件")

    if not unique:
        print("没有需要追加的域名（均已存在或已过滤）")
        return

    block = []
    for d in unique:
        block.append(f"""  {d}:
    title:
      method: xpath
      value: ''
    content:
      method: xpath
      value: ''""")

    append = "\n" + "\n".join(block)
    content = SELECTORS_PATH.read_text(encoding="utf-8")
    if not content.endswith("\n"):
        content += "\n"
    SELECTORS_PATH.write_text(content + append, encoding="utf-8")
    print(f"已追加 {len(unique)} 个域名到 {SELECTORS_PATH}")
    for d in unique:
        print(f"  - {d}")

if __name__ == "__main__":
    main()
