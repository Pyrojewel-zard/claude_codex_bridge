#!/usr/bin/env python3
"""
抓取 Herdr 中文文档 (https://herdr.dev/zh-cn/docs/) 并保存为本地 Markdown 文件。
来源: sitemap.xml → 逐页下载 → 提取 <main> → html2text 转 MD
"""

import html2text
import re
import os
import sys
import time
import json
import io
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urljoin

# 修复 Windows 控制台 GBK 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_URL = "https://herdr.dev"
DOCS_BASE = f"{BASE_URL}/zh-cn/docs/"
SITEMAP_URL = f"{BASE_URL}/sitemap-0.xml"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "herdr-docs"

# 伪造 UA 避免被某些 CDN 拦截
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 页面标题映射（从 sitemap URL 路径自动推断 + 手动覆盖）
MANUAL_TITLES = {
    "": "概览",
    "install": "安装 Herdr",
    "quick-start": "快速开始",
    "concepts": "核心概念",
    "configuration": "配置 Herdr",
    "config-reference": "配置参考",
    "agents": "理解智能体",
    "agent-automation": "智能体自动化",
    "agent-skill": "智能体技能",
    "session-state": "会话状态",
    "persistence-remote": "远程持久化",
    "socket-api": "Socket API 指南",
    "plugins": "编写插件",
    "marketplace": "发布插件",
    "integrations": "集成",
    "keyboard": "按键绑定",
    "cli-reference": "CLI 参考",
    "how-to-work": "工作原理",
    "troubleshooting": "故障排除",
    "windows-beta": "Windows 测试版",
}


def fetch_url(url: str, max_retries: int = 3) -> str:
    """下载 URL 并返回 HTML 文本"""
    for attempt in range(max_retries):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            print(f"    重试 {attempt + 1}/{max_retries}: {e}")
            time.sleep(2)


def get_doc_urls() -> list[tuple[str, str]]:
    """从 sitemap 获取所有中文文档的 (路径slug, 完整URL) 列表"""
    xml = fetch_url(SITEMAP_URL)
    urls = re.findall(r"<loc>(.*?)</loc>", xml)
    doc_urls = [u for u in urls if "/zh-cn/docs/" in u]
    # 去掉末尾斜杠，提取 slug
    result = []
    for url in sorted(doc_urls):
        url_clean = url.rstrip("/")
        # 使用 removesuffix 安全地提取 slug（处理首页 /zh-cn/docs 和 /zh-cn/docs/ 两种形式）
        prefix = f"{BASE_URL}/zh-cn/docs/"
        if url_clean.startswith(prefix):
            slug = url_clean[len(prefix):]
        elif url_clean == f"{BASE_URL}/zh-cn/docs":
            slug = ""
        else:
            slug = url_clean.replace(prefix, "")
        result.append((slug, url_clean))
    return result


def extract_main_html(html: str) -> str:
    """从页面 HTML 中提取 <main> 标签内容"""
    m = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL)
    if not m:
        # 回退：取 <body>
        m = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
        if not m:
            return html
    return m.group(1)


def clean_main_html(html: str) -> str:
    """
    清理提取出的 main 内容：
    - 去除 Expressive Code 的 figcaption（"Terminal window" 等）
    - 去除 prev/next 导航行
    - 去除"编辑此页"链接
    """
    # 移除 Expressive Code 的标题栏 (figcaption)
    html = re.sub(
        r'<figcaption[^>]*>.*?</figcaption>',
        "",
        html,
        flags=re.DOTALL,
    )
    # 移除页面底部的 prev/next 导航区域
    html = re.sub(
        r'<div[^>]*class="[^"]*pagination[^"]*"[^>]*>.*?</div>\s*</div>',
        "",
        html,
        flags=re.DOTALL,
    )
    # 移除单独的 prev/next 链接行
    html = re.sub(
        r'<a\s+href="[^"]*"[^>]*>\s*上一页[^<]*</a>',
        "",
        html,
        flags=re.DOTALL,
    )
    html = re.sub(
        r'<a\s+href="[^"]*"[^>]*>\s*下一页[^<]*</a>',
        "",
        html,
        flags=re.DOTALL,
    )
    # 移除 "编辑此页" 链接
    html = re.sub(
        r'<a\s+href="[^"]*github\.com[^"]*edit[^"]*"[^>]*>.*?</a>',
        "",
        html,
        flags=re.DOTALL,
    )
    # Remove translation disclaimer (wrapped in <div class="...n-notice...">)
    html = re.sub(
        r'<div[^>]*class="[^"]*notice[^"]*"[^>]*>\s*本页面的翻译由 LLM 生成.*?</div>',
        "",
        html,
        flags=re.DOTALL,
    )
    return html


def html_to_markdown(html: str, base_url: str = BASE_URL) -> str:
    """使用 html2text 将 HTML 转为 Markdown"""
    converter = html2text.HTML2Text()
    converter.body_width = 0  # 不自动折行
    converter.ignore_links = False
    converter.ignore_images = False
    converter.ignore_emphasis = False
    converter.protect_links = True
    converter.unicode_snob = True
    converter.mark_code = True
    converter.default_image_alt = ""

    # 将相对链接转为绝对链接
    md = converter.handle(html)

    # ——— Post-process cleanup ———

    # [code]...[/code] → ``` fenced code blocks (handle trailing whitespace)
    md = re.sub(r"\n\[code\]\s*\n", "\n```sh\n", md)
    md = re.sub(r"\n\[/code\]\s*\n", "\n```\n", md)

    # Remove "Section titled ..." a11y labels
    md = re.sub(r"\nSection titled .*?\n", "\n", md)

    # Remove "edit this page" links
    md = re.sub(r"\n\[.*?编辑此页.*?\]\([^)]+\)\n?", "", md)

    # Remove translation disclaimer (may appear at start of content, or after newline)
    md = re.sub(
        r"(?:^|\n)本页面的翻译由 LLM 生成[^\n]*\n?",
        "\n",
        md,
    )

    # Remove duplicate H1 from content (template already provides one)
    # Content H1 may be at string start (after translation removal) or after newline
    md = re.sub(r"(?:^|\n)# .*\n+", "\n", md, count=1)

    # Collapse extra blank lines
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def extract_page_title(html: str, slug: str) -> str:
    """从页面提取标题，优先用 MANUAL_TITLES"""
    if slug in MANUAL_TITLES:
        return MANUAL_TITLES[slug]

    # 尝试从 <h1> 提取
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    if m:
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        # 去掉 "Section titled …" 模式
        title = re.sub(r"Section titled\s*[「「""].*?[」」""]", "", title).strip()
        if title:
            return title

    # 从 <title> 提取
    m = re.search(r"<title>(.*?)</title>", html)
    if m:
        title = m.group(1).strip()
        title = re.sub(r"\s*\|.*$", "", title)  # "页面标题 | 站点名" → "页面标题"
        title = re.sub(r"\s*[–—\-]\s*.*$", "", title)
        return title

    return slug.replace("-", " ").title()


def make_filename(index: int, slug: str, title: str) -> str:
    """生成安全的文件名"""
    # 用序号 + 中文简称
    safe_slug = slug.replace("/", "-") or "index"
    return f"{index:02d}-{safe_slug}.md"


def scrape_all():
    """主流程：获取、转换、保存所有文档页面"""
    print("=" * 60)
    print("Herdr 文档抓取工具")
    print("=" * 60)

    # 1. 获取 URL 列表
    print("\n[1/4] 从 sitemap 获取页面列表...")
    doc_urls = get_doc_urls()
    print(f"  发现 {len(doc_urls)} 个中文文档页面")

    # 2. 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  输出目录: {OUTPUT_DIR}")

    # 3. 逐页下载并转换
    print(f"\n[2/4] 下载并转换 ({len(doc_urls)} 页)...")
    results = []
    failed = []

    for i, (slug, url) in enumerate(doc_urls, 1):
        print(f"  [{i:2d}/{len(doc_urls)}] {slug or '(index)'} ... ", end="", flush=True)

        try:
            # 下载
            html = fetch_url(url)

            # 提取标题
            title = extract_page_title(html, slug)

            # 提取并清理 main 内容
            main_html = extract_main_html(html)
            main_html = clean_main_html(main_html)

            # HTML → Markdown
            markdown = html_to_markdown(main_html)

            # 添加 YAML frontmatter
            final_md = f"""---
title: "{title}"
slug: "{slug}"
source: "{url}"
---

# {title}

{markdown}
"""
            filename = make_filename(i, slug, title)
            filepath = OUTPUT_DIR / filename

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(final_md)

            char_count = len(markdown)
            results.append(
                {
                    "index": i,
                    "slug": slug,
                    "title": title,
                    "url": url,
                    "file": filename,
                    "chars": char_count,
                }
            )
            print(f"✓ {char_count} 字符 → {filename}")

        except Exception as e:
            print(f"✗ 失败: {e}")
            failed.append({"index": i, "slug": slug, "url": url, "error": str(e)})

        # 礼貌延迟
        time.sleep(0.5)

    # 4. 生成索引页
    print(f"\n[3/4] 生成索引页...")
    index_lines = [
        "# Herdr 文档（本地镜像）\n",
        f"> 来源: {BASE_URL}/zh-cn/docs/  \n",
        f"> 抓取时间: {time.strftime('%Y-%m-%d %H:%M:%S')}  \n",
        f"> 页面总数: {len(results)}\n",
        "\n## 目录\n",
    ]

    for r in results:
        index_lines.append(f"- [{r['title']}]({r['file']})")

    if failed:
        index_lines.append("\n## 抓取失败\n")
        for f in failed:
            index_lines.append(f"- [{f['slug']}]({f['url']}) — {f['error']}")

    indexPath = OUTPUT_DIR / "README.md"
    with open(indexPath, "w", encoding="utf-8") as f:
        f.write("\n".join(index_lines) + "\n")

    # 5. 保存元数据
    print(f"[4/4] 保存元数据...")
    meta = {
        "source": BASE_URL + "/zh-cn/docs/",
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_pages": len(doc_urls),
        "success": len(results),
        "failed": len(failed),
        "pages": results,
    }
    if failed:
        meta["failures"] = failed

    with open(OUTPUT_DIR / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 输出报告
    print("\n" + "=" * 60)
    print(f"完成! 成功: {len(results)} 页, 失败: {len(failed)} 页")
    print(f"输出目录: {OUTPUT_DIR}")
    total_chars = sum(r["chars"] for r in results)
    print(f"总字符数: {total_chars}")
    print("=" * 60)

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(scrape_all())
