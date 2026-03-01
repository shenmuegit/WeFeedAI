#!/usr/bin/env python3
"""分析 no_content_domains.txt 文件，按缺失类型分组显示"""

from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple


def analyze_no_content_domains(file_path: str = "config/no_content_domains.txt"):
    """分析 no_content_domains.txt 文件并按类型分组
    
    Args:
        file_path: 文件路径
    """
    file_path = Path(__file__).parent.parent / file_path
    
    if not file_path.exists():
        print(f"文件不存在: {file_path}")
        return
    
    # 分组存储
    groups = {
        "title_and_content_missing": [],  # 标题和内容同时没有
        "content_missing": [],            # 内容没有（但标题有）
        "title_missing": [],              # 标题没有（但内容有）
        "cover_missing": [],              # 封面没有（标题和内容都有）
        "other": []                       # 其他情况
    }
    
    # 读取并解析文件
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            # 解析格式：domain|reason|url|timestamp
            parts = line.split('|')
            if len(parts) < 4:
                print(f"警告：第 {line_num} 行格式不正确: {line}")
                continue
            
            domain = parts[0]
            reasons = parts[1].split(',')
            url = parts[2]
            timestamp = parts[3]
            
            # 判断缺失类型
            has_title_missing = 'title_missing' in reasons or 'title_empty' in reasons
            has_content_missing = 'content_missing' in reasons or 'content_empty' in reasons
            has_cover_missing = 'cover_missing' in reasons or 'cover_empty' in reasons
            
            record = {
                'domain': domain,
                'url': url,
                'timestamp': timestamp,
                'reasons': reasons
            }
            
            # 分类
            if has_title_missing and has_content_missing:
                groups["title_and_content_missing"].append(record)
            elif has_content_missing and not has_title_missing:
                groups["content_missing"].append(record)
            elif has_title_missing and not has_content_missing:
                groups["title_missing"].append(record)
            elif has_cover_missing and not has_title_missing and not has_content_missing:
                groups["cover_missing"].append(record)
            else:
                groups["other"].append(record)
    
    # 显示分组结果
    print("=" * 80)
    print("no_content_domains.txt 分组分析结果")
    print("=" * 80)
    print()
    
    # 1. 标题和内容同时没有的
    if groups["title_and_content_missing"]:
        print(f"【标题和内容同时没有】 ({len(groups['title_and_content_missing'])} 条)")
        print("-" * 80)
        for record in groups["title_and_content_missing"]:
            print(f"  • {record['domain']}")
            print(f"    原因: {', '.join(record['reasons'])}")
            print(f"    URL: {record['url']}")
            print(f"    时间: {record['timestamp']}")
            print()
    
    # 2. 内容没有的（但标题有）
    if groups["content_missing"]:
        print(f"【内容没有的】（标题有） ({len(groups['content_missing'])} 条)")
        print("-" * 80)
        for record in groups["content_missing"]:
            print(f"  • {record['domain']}")
            print(f"    原因: {', '.join(record['reasons'])}")
            print(f"    URL: {record['url']}")
            print(f"    时间: {record['timestamp']}")
            print()
    
    # 3. 标题没有的（但内容有）
    if groups["title_missing"]:
        print(f"【标题没有的】（内容有） ({len(groups['title_missing'])} 条)")
        print("-" * 80)
        for record in groups["title_missing"]:
            print(f"  • {record['domain']}")
            print(f"    原因: {', '.join(record['reasons'])}")
            print(f"    URL: {record['url']}")
            print(f"    时间: {record['timestamp']}")
            print()
    
    # 4. 封面没有的（标题和内容都有）
    if groups["cover_missing"]:
        print(f"【封面没有的】（标题和内容都有） ({len(groups['cover_missing'])} 条)")
        print("-" * 80)
        for record in groups["cover_missing"]:
            print(f"  • {record['domain']}")
            print(f"    原因: {', '.join(record['reasons'])}")
            print(f"    URL: {record['url']}")
            print(f"    时间: {record['timestamp']}")
            print()
    
    # 5. 其他情况
    if groups["other"]:
        print(f"【其他情况】 ({len(groups['other'])} 条)")
        print("-" * 80)
        for record in groups["other"]:
            print(f"  • {record['domain']}")
            print(f"    原因: {', '.join(record['reasons'])}")
            print(f"    URL: {record['url']}")
            print(f"    时间: {record['timestamp']}")
            print()
    
    # 统计摘要
    print("=" * 80)
    print("统计摘要")
    print("=" * 80)
    print(f"标题和内容同时没有: {len(groups['title_and_content_missing'])} 条")
    print(f"内容没有（标题有）: {len(groups['content_missing'])} 条")
    print(f"标题没有（内容有）: {len(groups['title_missing'])} 条")
    print(f"封面没有（标题和内容都有）: {len(groups['cover_missing'])} 条")
    print(f"其他情况: {len(groups['other'])} 条")
    print(f"总计: {sum(len(v) for v in groups.values())} 条")
    print()


if __name__ == "__main__":
    analyze_no_content_domains()


