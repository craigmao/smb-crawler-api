"""
SMB 情报爬虫 API — Vercel Python Serverless

策略: 用行业关键词主动搜索各平台, 而非过滤泛热榜
数据源:
  搜索类: 微博搜索 / 知乎搜索 / B站搜索 / 百度搜索 / 头条搜索
  热榜类: 保留作为"大盘感知"辅助
"""
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import json
import re
import time
import urllib.parse
from datetime import datetime
from typing import List

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

# ====== 搜索关键词 (轮换使用) ======
SEARCH_KEYWORDS = [
    # 品牌 & 竞对
    "酷家乐", "三维家", "躺平设计家",
    "欧派家居", "索菲亚家居", "尚品宅配",
    # 核心品类
    "全屋定制", "装修设计", "室内设计",
    "定制家具", "智能家居",
    # 用户需求场景
    "装修效果图", "装修攻略",
    "小户型装修", "厨房设计", "客厅设计",
    # 行业信号
    "家居数字化", "AI设计 家居",
    "家居展 2025", "建材市场",
    "精装房 政策", "存量房 装修",
]

# 每次采集随机取一批关键词避免重复
def get_search_batch() -> List[str]:
    """根据当前小时轮换关键词批次"""
    hour = datetime.now().hour
    batch_size = 6
    start = (hour * batch_size) % len(SEARCH_KEYWORDS)
    batch = SEARCH_KEYWORDS[start:start + batch_size]
    if len(batch) < batch_size:
        batch += SEARCH_KEYWORDS[:batch_size - len(batch)]
    return batch


# ====== 缓存 ======
_cache: dict = {}
CACHE_TTL = 600

def cached(key):
    if key in _cache and time.time() - _cache[key]["t"] < CACHE_TTL:
        return _cache[key]["d"]
    return None

def cache_set(key, data):
    _cache[key] = {"d": data, "t": time.time()}


# ============================================================
# 搜索类采集器 — 用行业关键词搜索各平台
# ============================================================

async def search_weibo(keywords: List[str]) -> list:
    """微博综合搜索"""
    items = []
    async with httpx.AsyncClient(timeout=10) as c:
        for kw in keywords:
            try:
                r = await c.get(
                    f"https://m.weibo.cn/api/container/getIndex?containerid=100103type%3D1%26q%3D{urllib.parse.quote(kw)}&page_type=searchall",
                    headers={"User-Agent": UA, "Referer": "https://m.weibo.cn/"},
                )
                data = r.json()
                cards = data.get("data", {}).get("cards", [])
                for card in cards:
                    if card.get("card_type") == 9:
                        mblog = card.get("mblog", {})
                        text = re.sub(r"<[^>]+>", "", mblog.get("text", ""))
                        items.append({
                            "title": text[:120],
                            "url": f"https://m.weibo.cn/detail/{mblog.get('id', '')}",
                            "desc": f"@{mblog.get('user', {}).get('screen_name', '')}",
                            "hot": mblog.get("reposts_count", 0) + mblog.get("comments_count", 0) + mblog.get("attitudes_count", 0),
                            "reposts": mblog.get("reposts_count", 0),
                            "comments": mblog.get("comments_count", 0),
                            "likes": mblog.get("attitudes_count", 0),
                            "source": "weibo",
                            "keyword": kw,
                        })
                    elif card.get("card_type") == 11:
                        for inner in card.get("card_group", []):
                            if inner.get("card_type") == 9:
                                mblog = inner.get("mblog", {})
                                text = re.sub(r"<[^>]+>", "", mblog.get("text", ""))
                                items.append({
                                    "title": text[:120],
                                    "url": f"https://m.weibo.cn/detail/{mblog.get('id', '')}",
                                    "desc": f"@{mblog.get('user', {}).get('screen_name', '')}",
                                    "hot": mblog.get("reposts_count", 0) + mblog.get("comments_count", 0) + mblog.get("attitudes_count", 0),
                                    "source": "weibo",
                                    "keyword": kw,
                                })
            except Exception as e:
                print(f"[weibo search] {kw}: {e}")
    return items


async def search_zhihu(keywords: List[str]) -> list:
    """知乎搜索"""
    items = []
    async with httpx.AsyncClient(timeout=10) as c:
        for kw in keywords:
            try:
                r = await c.get(
                    f"https://api.zhihu.com/search_v3?t=general&q={urllib.parse.quote(kw)}&correction=1&offset=0&limit=10",
                    headers={"User-Agent": UA},
                )
                data = r.json()
                for entry in data.get("data", []):
                    obj = entry.get("object", {})
                    title = obj.get("title") or obj.get("question", {}).get("title", "")
                    if not title:
                        continue
                    title = re.sub(r"<[^>]+>", "", title)
                    excerpt = re.sub(r"<[^>]+>", "", obj.get("excerpt", "") or obj.get("content", "") or "")
                    url = obj.get("url", "")
                    if "zhihu.com" not in url and obj.get("id"):
                        qid = obj.get("question", {}).get("id", obj.get("id", ""))
                        url = f"https://www.zhihu.com/question/{qid}"
                    items.append({
                        "title": title[:150],
                        "url": url,
                        "excerpt": excerpt[:200],
                        "hot": obj.get("voteup_count", 0),
                        "comments": obj.get("comment_count", 0),
                        "source": "zhihu",
                        "keyword": kw,
                    })
            except Exception as e:
                print(f"[zhihu search] {kw}: {e}")
    return items


async def search_bilibili(keywords: List[str]) -> list:
    """B站搜索"""
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
                    title = re.sub(r"<[^>]+>", "", v.get("title", ""))
                    items.append({
                        "title": title[:150],
                        "url": f"https://www.bilibili.com/video/{v.get('bvid', '')}",
                        "desc": v.get("description", "")[:200],
                        "owner": v.get("author", ""),
                        "view": v.get("play", 0),
                        "like": v.get("like", 0),
                        "danmaku": v.get("video_review", 0),
                        "source": "bilibili",
                        "keyword": kw,
                    })
            except Exception as e:
                print(f"[bilibili search] {kw}: {e}")
    return items


async def search_toutiao(keywords: List[str]) -> list:
    """头条搜索"""
    items = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        for kw in keywords:
            try:
                r = await c.get(
                    f"https://www.toutiao.com/api/search/content/?aid=24&keyword={urllib.parse.quote(kw)}&count=10&search_id=0",
                    headers={"User-Agent": UA, "Referer": "https://www.toutiao.com/"},
                )
                data = r.json()
                for item in data.get("data", []):
                    title = item.get("title", "")
                    if not title:
                        continue
                    items.append({
                        "title": title[:150],
                        "url": item.get("article_url", "") or item.get("display_url", "") or f"https://www.toutiao.com/article/{item.get('item_id', '')}",
                        "desc": (item.get("abstract", "") or "")[:200],
                        "source": "toutiao",
                        "keyword": kw,
                    })
            except Exception as e:
                print(f"[toutiao search] {kw}: {e}")
    return items


async def search_baidu(keywords: List[str]) -> list:
    """百度资讯搜索"""
    items = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        for kw in keywords:
            try:
                r = await c.get(
                    f"https://www.baidu.com/s?wd={urllib.parse.quote(kw)}&tn=news&rtt=4&bsst=2",
                    headers={"User-Agent": UA},
                )
                html = r.text
                # 从百度搜索结果提取标题和链接
                results = re.findall(r'<h3[^>]*><a[^>]*href="([^"]*)"[^>]*>(.*?)</a></h3>', html)
                for url, title_html in results[:8]:
                    title = re.sub(r"<[^>]+>", "", title_html).strip()
                    if title:
                        items.append({
                            "title": title[:150],
                            "url": url,
                            "source": "baidu",
                            "keyword": kw,
                        })
            except Exception as e:
                print(f"[baidu search] {kw}: {e}")
    return items


# ============================================================
# 热榜类采集器 — 保留作为大盘感知
# ============================================================

async def fetch_toutiao_hot() -> list:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc", headers={"User-Agent": UA})
        return [{"title": e.get("Title", ""), "url": e.get("Url", ""), "hot": e.get("HotValue", 0), "source": "toutiao_hot"} for e in r.json().get("data", [])]


async def fetch_weibo_hot() -> list:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://weibo.com/ajax/side/hotSearch", headers={"User-Agent": UA, "Referer": "https://weibo.com/"})
        return [{"title": e.get("word", ""), "url": f"https://s.weibo.com/weibo?q={e.get('word', '')}", "hot": e.get("raw_hot", 0), "source": "weibo_hot"} for e in r.json().get("data", {}).get("realtime", [])]


async def fetch_douyin_hot() -> list:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        csrf = ""
        try:
            lr = await c.get("https://www.douyin.com/passport/general/login_guiding_strategy/?aid=6383", headers={"User-Agent": UA})
            tm = re.search(r"passport_csrf_token=([^;]+)", lr.headers.get("set-cookie", ""))
            csrf = tm.group(1) if tm else ""
        except Exception:
            pass
        h = {"User-Agent": UA, "Referer": "https://www.douyin.com/"}
        if csrf:
            h["Cookie"] = f"passport_csrf_token={csrf}"
        r = await c.get("https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383&channel=channel_pc_web&detail_list=1", headers=h)
        return [{"title": w.get("word", ""), "url": f"https://www.douyin.com/search/{w.get('word', '')}", "hot": w.get("hot_value", 0), "source": "douyin_hot"} for w in r.json().get("data", {}).get("word_list", [])]


# ============================================================
# API 端点
# ============================================================

@app.get("/api/all")
async def api_all():
    """核心端点: 行业搜索 + 热榜行业过滤"""
    c = cached("all")
    if c: return c

    kw_batch = get_search_batch()

    # 并行: 搜索(5平台) + 热榜(3平台)
    results = await asyncio.gather(
        search_weibo(kw_batch),
        search_zhihu(kw_batch),
        search_bilibili(kw_batch),
        search_toutiao(kw_batch),
        search_baidu(kw_batch),
        fetch_toutiao_hot(),
        fetch_weibo_hot(),
        fetch_douyin_hot(),
        return_exceptions=True,
    )

    names = ["weibo_search", "zhihu_search", "bilibili_search", "toutiao_search", "baidu_search", "toutiao_hot", "weibo_hot", "douyin_hot"]

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
        "keywords_used": kw_batch,
        "report": report,
        "timestamp": datetime.now().isoformat(),
    }
    cache_set("all", result)
    return result


@app.get("/api/search")
async def api_search(keyword: str = Query(..., description="自定义搜索关键词")):
    """自定义关键词搜索全平台"""
    cache_key = f"search_{keyword}"
    c = cached(cache_key)
    if c: return c

    kws = [keyword]
    results = await asyncio.gather(
        search_weibo(kws),
        search_zhihu(kws),
        search_bilibili(kws),
        search_toutiao(kws),
        search_baidu(kws),
        return_exceptions=True,
    )
    names = ["weibo", "zhihu", "bilibili", "toutiao", "baidu"]
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


@app.get("/api/hot")
async def api_hot():
    """纯热榜 (大盘感知)"""
    c = cached("hot")
    if c: return c

    results = await asyncio.gather(
        fetch_toutiao_hot(), fetch_weibo_hot(), fetch_douyin_hot(),
        return_exceptions=True,
    )
    items = []
    for r in results:
        if isinstance(r, list):
            items.extend(r)
    result = {"code": 0, "data": items, "total": len(items)}
    cache_set("hot", result)
    return result


@app.get("/api/health")
async def health():
    return {"status": "ok", "ts": datetime.now().isoformat(), "keywords": SEARCH_KEYWORDS}
