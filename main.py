"""
SMB 情报爬虫 API 服务
部署在国内服务器（阿里云/腾讯云），为 Vercel 前端提供中文平台数据

数据源:
1. 头条热榜    /api/toutiao
2. 微博热搜    /api/weibo
3. 知乎热榜    /api/zhihu
4. 百度热搜    /api/baidu
5. B站热门     /api/bilibili
6. 抖音热搜    /api/douyin
7. 小红书搜索  /api/xiaohongshu
8. 微信公众号  /api/wechat  (需额外配置)
9. 少数派      /api/sspai
10. 掘金       /api/juejin
11. 36氪       /api/36kr
12. 全量聚合   /api/all
"""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import json
import re
import time
import hashlib
import os
from datetime import datetime
from typing import Optional

app = FastAPI(title="SMB 情报爬虫 API", version="1.0")

# CORS - 允许 Vercel 前端调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA}

# ====== 内存缓存 ======
_cache: dict = {}
CACHE_TTL = 600  # 10分钟


def get_cached(key: str):
    if key in _cache and time.time() - _cache[key]["t"] < CACHE_TTL:
        return _cache[key]["data"]
    return None


def set_cache(key: str, data):
    _cache[key] = {"data": data, "t": time.time()}


# ====== 1. 头条热榜 ======
@app.get("/api/toutiao")
async def toutiao():
    cached = get_cached("toutiao")
    if cached:
        return cached
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
            headers=HEADERS,
        )
        data = r.json()
        items = []
        for entry in data.get("data", []):
            items.append({
                "title": entry.get("Title", ""),
                "url": entry.get("Url", ""),
                "hot": entry.get("HotValue", 0),
                "source": "toutiao",
            })
        result = {"code": 0, "data": items, "total": len(items)}
        set_cache("toutiao", result)
        return result


# ====== 2. 微博热搜 ======
@app.get("/api/weibo")
async def weibo():
    cached = get_cached("weibo")
    if cached:
        return cached
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://weibo.com/ajax/side/hotSearch",
            headers={**HEADERS, "Referer": "https://weibo.com/"},
        )
        data = r.json()
        items = []
        for entry in data.get("data", {}).get("realtime", []):
            word = entry.get("word", "")
            items.append({
                "title": word,
                "url": f"https://s.weibo.com/weibo?q={word}",
                "hot": entry.get("raw_hot", 0),
                "label": entry.get("label_name", ""),
                "source": "weibo",
            })
        result = {"code": 0, "data": items, "total": len(items)}
        set_cache("weibo", result)
        return result


# ====== 3. 知乎热榜 ======
@app.get("/api/zhihu")
async def zhihu():
    cached = get_cached("zhihu")
    if cached:
        return cached
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://api.zhihu.com/topstory/hot-lists/total?limit=50",
            headers={**HEADERS, "Accept": "application/json"},
        )
        data = r.json()
        items = []
        for entry in data.get("data", []):
            target = entry.get("target", {})
            items.append({
                "title": target.get("title", ""),
                "url": f"https://www.zhihu.com/question/{target.get('id', '')}",
                "excerpt": (target.get("excerpt", "") or "")[:200],
                "hot": entry.get("detail_text", ""),
                "source": "zhihu",
            })
        result = {"code": 0, "data": items, "total": len(items)}
        set_cache("zhihu", result)
        return result


# ====== 4. 百度热搜 ======
@app.get("/api/baidu")
async def baidu():
    cached = get_cached("baidu")
    if cached:
        return cached
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://top.baidu.com/board?tab=realtime",
            headers={**HEADERS, "Accept": "text/html"},
        )
        html = r.text
        match = re.search(r"<!--s-data:(.*?)-->", html, re.DOTALL)
        items = []
        if match:
            json_data = json.loads(match.group(1))
            for card in json_data.get("data", {}).get("cards", []):
                for content in card.get("content", []):
                    items.append({
                        "title": content.get("word", content.get("query", "")),
                        "url": content.get("url", ""),
                        "desc": (content.get("desc", "") or "")[:200],
                        "hot": content.get("hotScore", 0),
                        "source": "baidu",
                    })
        result = {"code": 0, "data": items, "total": len(items)}
        set_cache("baidu", result)
        return result


# ====== 5. B站热门 ======
@app.get("/api/bilibili")
async def bilibili():
    cached = get_cached("bilibili")
    if cached:
        return cached
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://api.bilibili.com/x/web-interface/popular?ps=50&pn=1",
            headers={**HEADERS, "Referer": "https://www.bilibili.com/"},
        )
        data = r.json()
        items = []
        if data.get("code") == 0:
            for video in data.get("data", {}).get("list", []):
                stat = video.get("stat", {})
                items.append({
                    "title": video.get("title", ""),
                    "url": video.get("short_link_v2", "") or f"https://www.bilibili.com/video/{video.get('bvid', '')}",
                    "desc": (video.get("desc", "") or "")[:200],
                    "owner": video.get("owner", {}).get("name", ""),
                    "view": stat.get("view", 0),
                    "like": stat.get("like", 0),
                    "danmaku": stat.get("danmaku", 0),
                    "source": "bilibili",
                })
        result = {"code": 0, "data": items, "total": len(items)}
        set_cache("bilibili", result)
        return result


# ====== 6. 抖音热搜 ======
@app.get("/api/douyin")
async def douyin():
    cached = get_cached("douyin")
    if cached:
        return cached
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        # 先拿 csrf token
        csrf = ""
        try:
            login_r = await client.get(
                "https://www.douyin.com/passport/general/login_guiding_strategy/?aid=6383",
                headers=HEADERS,
            )
            m = re.search(r"passport_csrf_token=([^;]+)", login_r.headers.get("set-cookie", ""))
            csrf = m.group(1) if m else ""
        except Exception:
            pass

        headers = {**HEADERS, "Referer": "https://www.douyin.com/"}
        if csrf:
            headers["Cookie"] = f"passport_csrf_token={csrf}"

        r = await client.get(
            "https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383&channel=channel_pc_web&detail_list=1",
            headers=headers,
        )
        data = r.json()
        items = []
        for word in data.get("data", {}).get("word_list", []):
            items.append({
                "title": word.get("word", ""),
                "url": f"https://www.douyin.com/search/{word.get('word', '')}",
                "hot": word.get("hot_value", 0),
                "source": "douyin",
            })
        result = {"code": 0, "data": items, "total": len(items)}
        set_cache("douyin", result)
        return result


# ====== 7. 小红书热门/搜索 ======
@app.get("/api/xiaohongshu")
async def xiaohongshu(keyword: str = Query("家居设计", description="搜索关键词")):
    cache_key = f"xhs_{keyword}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    async with httpx.AsyncClient(timeout=10) as client:
        # 小红书 Web 搜索接口 (需要签名，这里用简化版)
        # 实际生产环境建议集成 MediaCrawler
        headers = {
            **HEADERS,
            "Referer": "https://www.xiaohongshu.com/",
            "Origin": "https://www.xiaohongshu.com",
        }
        # 小红书的 API 需要 x-s/x-t 签名，纯 HTTP 很难绕过
        # 这里提供搜索链接导引，深度采集需要 MediaCrawler
        items = []
        # 用预设的家居行业关键词生成搜索入口
        kw_list = [keyword] if keyword != "家居设计" else [
            "装修效果图", "全屋定制", "小户型设计", "厨房设计",
            "卫生间装修", "客厅设计", "卧室装修", "北欧风",
            "新中式装修", "极简风格", "智能家居", "酷家乐",
            "三维家", "设计师推荐", "装修避坑", "建材选购",
            "瓷砖挑选", "定制衣柜", "橱柜品牌", "灯光设计",
        ]
        for kw in kw_list:
            items.append({
                "title": f"小红书搜索: {kw}",
                "url": f"https://www.xiaohongshu.com/search_result?keyword={kw}&source=web_search_result_notes",
                "desc": f"小红书「{kw}」相关笔记（需集成 MediaCrawler 获取具体内容）",
                "hot": 0,
                "source": "xiaohongshu",
                "note": "深度采集需配置 MediaCrawler，当前为搜索入口",
            })
        result = {"code": 0, "data": items, "total": len(items), "note": "小红书需要签名验证，深度内容请集成 MediaCrawler"}
        set_cache(cache_key, result)
        return result


# ====== 8. 少数派 ======
@app.get("/api/sspai")
async def sspai():
    cached = get_cached("sspai")
    if cached:
        return cached
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://sspai.com/api/v1/article/tag/page/get?limit=20&offset=0&tag=%E7%83%AD%E9%97%A8%E6%96%87%E7%AB%A0"
        )
        data = r.json()
        items = []
        for article in data.get("data", []):
            items.append({
                "title": article.get("title", ""),
                "url": f"https://sspai.com/post/{article.get('id', '')}",
                "summary": (article.get("summary", "") or "")[:200],
                "likes": article.get("like_count", 0),
                "comments": article.get("comment_count", 0),
                "source": "sspai",
            })
        result = {"code": 0, "data": items, "total": len(items)}
        set_cache("sspai", result)
        return result


# ====== 9. 掘金 ======
@app.get("/api/juejin")
async def juejin():
    cached = get_cached("juejin")
    if cached:
        return cached
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot",
            json={},
            headers={**HEADERS, "Content-Type": "application/json"},
        )
        data = r.json()
        items = []
        for article in data.get("data", []):
            info = article.get("content", {})
            items.append({
                "title": info.get("title", ""),
                "url": f"https://juejin.cn/post/{info.get('content_id', '')}",
                "hot": article.get("content_counter", {}).get("hot_rank", 0),
                "source": "juejin",
            })
        result = {"code": 0, "data": items, "total": len(items)}
        set_cache("juejin", result)
        return result


# ====== 10. 36氪 ======
@app.get("/api/36kr")
async def kr36():
    cached = get_cached("36kr")
    if cached:
        return cached
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://36kr.com/api/newsflash?per_page=30",
            headers={**HEADERS, "Accept": "application/json"},
        )
        data = r.json()
        items = []
        for news in data.get("data", {}).get("items", []):
            items.append({
                "title": news.get("title", news.get("entity_name", "")),
                "url": news.get("news_url", f"https://36kr.com/newsflashes/{news.get('id', '')}"),
                "desc": (news.get("description", "") or "")[:200],
                "source": "36kr",
                "time": news.get("published_at", ""),
            })
        result = {"code": 0, "data": items, "total": len(items)}
        set_cache("36kr", result)
        return result


# ====== 全量聚合 ======
@app.get("/api/all")
async def collect_all():
    """并行采集所有数据源，返回聚合结果"""
    cached = get_cached("all")
    if cached:
        return cached

    results = await asyncio.gather(
        toutiao(),
        weibo(),
        zhihu(),
        baidu(),
        bilibili(),
        douyin(),
        sspai(),
        juejin(),
        kr36(),
        return_exceptions=True,
    )

    all_items = []
    report = {}
    source_names = ["toutiao", "weibo", "zhihu", "baidu", "bilibili", "douyin", "sspai", "juejin", "36kr"]

    for i, r in enumerate(results):
        name = source_names[i]
        if isinstance(r, Exception):
            report[name] = f"error: {str(r)}"
        elif isinstance(r, dict):
            items = r.get("data", [])
            all_items.extend(items)
            report[name] = len(items)
        else:
            report[name] = 0

    result = {
        "code": 0,
        "data": all_items,
        "total": len(all_items),
        "report": report,
        "timestamp": datetime.now().isoformat(),
    }
    set_cache("all", result)
    return result


# ====== 健康检查 ======
@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat(), "cache_keys": list(_cache.keys())}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
