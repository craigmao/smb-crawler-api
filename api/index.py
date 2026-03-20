"""
SMB 情报爬虫 API v4 — 新闻聚合架构

策略: Google News RSS + 36kr RSS + 搜狗微信 + B站
- 主力源: Google News RSS (免费、稳定、时效性强、来自正规媒体)
- 补充源: 36kr RSS (科技商业), 搜狗微信 (公众号), B站 (用户声音)

关键词分3层:
  Tier 1 竞品监控: 酷家乐, 三维家, 躺平设计家 等
  Tier 2 行业趋势: 全屋定制, 家居数字化, AI家装设计 等
  Tier 3 客户动态: 欧派, 索菲亚, 尚品宅配 等头部企业
"""
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

# ====== 搜索关键词 (3层分类) ======
SEARCH_KEYWORDS = [
    # === Tier 1: 竞品监控 ===
    "酷家乐", "三维家", "躺平设计家", "打扮家", "家居云设计",

    # === Tier 2: 行业趋势 ===
    "全屋定制", "装修设计软件", "家居数字化", "AI家装设计",
    "定制家居", "门店设计工具", "BIM家装", "整装设计",

    # === Tier 3: 客户动态 ===
    "欧派家居", "索菲亚家居", "尚品宅配", "志邦家居",
    "金牌橱柜", "我乐家居", "好莱客", "皮阿诺",
]

# ====== HTML 实体解码 ======
def decode_entities(s: str) -> str:
    if not s:
        return s
    return (s.replace("&ldquo;", "\u201c").replace("&rdquo;", "\u201d")
            .replace("&lsquo;", "\u2018").replace("&rsquo;", "\u2019")
            .replace("&middot;", "\u00b7").replace("&mdash;", "\u2014").replace("&ndash;", "\u2013")
            .replace("&hellip;", "\u2026").replace("&nbsp;", " ")
            .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'"))


# ====== 缓存 ======
_cache: dict = {}
CACHE_TTL = 1800  # 30分钟缓存

def cached(key):
    if key in _cache and time.time() - _cache[key]["t"] < CACHE_TTL:
        return _cache[key]["d"]
    return None

def cache_set(key, data):
    _cache[key] = {"d": data, "t": time.time()}


# ============================================================
# 数据源 1: Google News RSS (主力)
# 免费、无反爬、返回最新新闻、来自正规媒体
# ============================================================
async def fetch_google_news(keywords: List[str]) -> list:
    """Google News RSS 搜索 — 每个关键词返回最新新闻"""
    items = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        for kw in keywords:
            try:
                url = f"https://news.google.com/rss/search?q={urllib.parse.quote(kw)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
                r = await c.get(url, headers={"User-Agent": UA})
                if r.status_code != 200:
                    continue
                root = ET.fromstring(r.text)
                for item in root.findall(".//item")[:15]:  # 每关键词最多15条
                    title = item.find("title").text or ""
                    link = item.find("link").text or ""
                    pubdate = item.find("pubDate").text or ""
                    source_el = item.find("source")
                    source_name = source_el.text if source_el is not None else ""

                    title = decode_entities(re.sub(r"<[^>]+>", "", title).strip())
                    if title and len(title) > 5:
                        items.append({
                            "title": title[:150],
                            "url": link,
                            "source": "google_news",
                            "media": source_name,
                            "pubdate": pubdate,
                            "keyword": kw,
                        })
            except Exception as e:
                print(f"[google_news] {kw}: {e}")
    return items


# ============================================================
# 数据源 2: 36kr RSS (科技商业新闻)
# ============================================================
async def fetch_36kr_rss() -> list:
    """36kr RSS — 科技商业新闻，筛选行业相关"""
    items = []
    industry_kw = ["家居", "装修", "设计", "定制", "AI", "数字化", "家装", "建材",
                   "智能家居", "SaaS", "云", "3D", "BIM", "家具", "整装", "软装"]
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get("https://36kr.com/feed", headers={"User-Agent": UA})
            if r.status_code == 200:
                root = ET.fromstring(r.text)
                for item in root.findall(".//item"):
                    title = item.find("title").text or ""
                    link = item.find("link").text or ""
                    desc = ""
                    desc_el = item.find("description")
                    if desc_el is not None and desc_el.text:
                        desc = re.sub(r"<[^>]+>", "", desc_el.text)[:200]
                    pubdate = ""
                    pd_el = item.find("pubDate")
                    if pd_el is not None and pd_el.text:
                        pubdate = pd_el.text

                    # 只保留和家居/设计/AI相关的
                    combined = title + desc
                    if any(k in combined for k in industry_kw):
                        items.append({
                            "title": decode_entities(title[:150]),
                            "url": link,
                            "desc": desc[:200],
                            "source": "36kr",
                            "media": "36氪",
                            "pubdate": pubdate,
                            "keyword": "36kr",
                        })
    except Exception as e:
        print(f"[36kr] {e}")
    return items


# ============================================================
# 数据源 3: 搜狗微信搜索 (保留，微信独家内容)
# ============================================================
async def search_sogou_wechat(keywords: List[str]) -> list:
    """搜狗微信公众号文章搜索"""
    items = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        for kw in keywords:
            try:
                r = await c.get(
                    f"https://weixin.sogou.com/weixin?type=2&query={urllib.parse.quote(kw)}",
                    headers={"User-Agent": UA, "Referer": "https://weixin.sogou.com/"},
                )
                if r.status_code != 200:
                    continue
                html = r.text
                results = re.findall(
                    r'<h3>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?</h3>',
                    html, re.DOTALL
                )
                if not results:
                    results = re.findall(
                        r'<a[^>]*href="(https?://mp\.weixin\.qq\.com[^"]*)"[^>]*>(.*?)</a>',
                        html, re.DOTALL
                    )
                for url, title_html in results[:10]:
                    title = decode_entities(re.sub(r"<[^>]+>", "", title_html).strip())
                    if title and len(title) > 3:
                        full_url = url
                        if url.startswith("/"):
                            full_url = f"https://weixin.sogou.com{url}"
                        elif not url.startswith("http"):
                            full_url = f"https://weixin.sogou.com/{url}"
                        items.append({
                            "title": title[:150],
                            "url": full_url,
                            "source": "wechat",
                            "media": "微信公众号",
                            "keyword": kw,
                        })
            except Exception as e:
                print(f"[sogou wechat] {kw}: {e}")
    return items


# ============================================================
# 数据源 4: B站搜索 (用户声音)
# ============================================================
async def search_bilibili(keywords: List[str]) -> list:
    """B站搜索 — 用户声音和行业视频"""
    items = []
    async with httpx.AsyncClient(timeout=10) as c:
        for kw in keywords:
            try:
                r = await c.get(
                    f"https://api.bilibili.com/x/web-interface/wbi/search/type?search_type=video&keyword={urllib.parse.quote(kw)}&page=1&page_size=10",
                    headers={"User-Agent": UA, "Referer": "https://search.bilibili.com/"},
                )
                data = r.json()
                for v in data.get("data", {}).get("result", []):
                    title = decode_entities(re.sub(r"<[^>]+>", "", v.get("title", "")))
                    items.append({
                        "title": title[:150],
                        "url": f"https://www.bilibili.com/video/{v.get('bvid', '')}",
                        "desc": v.get("description", "")[:200],
                        "owner": v.get("author", ""),
                        "view": v.get("play", 0),
                        "like": v.get("like", 0),
                        "source": "bilibili",
                        "media": v.get("author", ""),
                        "keyword": kw,
                    })
            except Exception as e:
                print(f"[bilibili] {kw}: {e}")
    return items


# ============================================================
# API 端点
# ============================================================

@app.get("/api/all")
async def api_all():
    """核心端点: 新闻聚合 + 社交平台搜索"""
    c = cached("all")
    if c:
        return c

    # 所有关键词都用（不再轮换，Google News RSS没有反爬限制）
    kw_all = SEARCH_KEYWORDS
    # 竞品关键词子集用于微信和B站（控制请求量）
    kw_core = SEARCH_KEYWORDS[:5]  # 竞品 + 头部关键词

    # 并行采集4个数据源
    results = await asyncio.gather(
        fetch_google_news(kw_all),     # 全量关键词 → Google News
        fetch_36kr_rss(),               # 36kr 行业筛选
        search_sogou_wechat(kw_core),   # 核心关键词 → 微信
        search_bilibili(kw_core),       # 核心关键词 → B站
        return_exceptions=True,
    )

    names = ["google_news", "36kr", "wechat", "bilibili"]
    all_items = []
    report = {}

    for i, name in enumerate(names):
        r = results[i]
        if isinstance(r, Exception):
            report[name] = f"error: {str(r)[:60]}"
        elif isinstance(r, list):
            all_items.extend(r)
            report[name] = len(r)
        else:
            report[name] = 0

    # 去重 (按标题前30字符)
    seen = set()
    unique = []
    for item in all_items:
        key = item.get("title", "")[:30]
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    result = {
        "code": 0,
        "data": unique,
        "total": len(unique),
        "keywords_used": kw_all,
        "report": report,
        "version": "4.0",
        "timestamp": datetime.now().isoformat(),
    }
    cache_set("all", result)
    return result


@app.get("/api/search")
async def api_search(keyword: str = Query(..., description="自定义搜索关键词")):
    """自定义关键词搜索"""
    cache_key = f"search_{keyword}"
    c = cached(cache_key)
    if c:
        return c

    kws = [keyword]
    results = await asyncio.gather(
        fetch_google_news(kws),
        search_sogou_wechat(kws),
        search_bilibili(kws),
        return_exceptions=True,
    )
    names = ["google_news", "wechat", "bilibili"]
    all_items = []
    report = {}
    for i, name in enumerate(names):
        r = results[i]
        if isinstance(r, Exception):
            report[name] = f"error: {str(r)[:60]}"
        elif isinstance(r, list):
            all_items.extend(r)
            report[name] = len(r)
        else:
            report[name] = 0

    result = {"code": 0, "data": all_items, "total": len(all_items), "keyword": keyword, "report": report}
    cache_set(cache_key, result)
    return result


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "4.0",
        "sources": ["google_news", "36kr", "wechat", "bilibili"],
        "ts": datetime.now().isoformat(),
        "keywords": SEARCH_KEYWORDS,
    }
