"""
Vercel Serverless Function — SMB 情报爬虫 API
自动路由: /api/* → 本文件处理
"""
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import json
import re
import time
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

# ====== 行业关键词过滤 ======
# 酷家乐 SMB 关注的行业领域
INDUSTRY_KEYWORDS = [
    # 品牌 & 竞对
    "酷家乐", "kujiale", "三维家", "打扮家", "爱福窝", "躺平设计家", "知户型",
    "欧派", "索菲亚", "尚品宅配", "维意定制", "好莱客", "金牌厨柜", "志邦",
    "我乐家居", "皮阿诺", "顶固", "百得胜", "诗尼曼", "冠特", "艾依格",
    "红星美凯龙", "居然之家", "富森美", "月星家居",
    # 行业品类
    "全屋定制", "定制家具", "定制家居", "家装设计", "装修设计", "室内设计",
    "装修效果图", "装修公司", "家装公司", "整装", "硬装", "软装",
    "橱柜", "衣柜", "木门", "门窗", "地板", "瓷砖", "岩板",
    "墙纸", "墙布", "窗帘", "涂料", "硅藻泥", "乳胶漆",
    "灯具", "照明", "卫浴", "厨电", "暖通", "新风", "净水",
    "家具", "沙发", "床", "餐桌", "家纺", "家饰",
    "建材", "家居", "家装", "装修", "装饰",
    # 技术
    "AI设计", "AI出图", "AI渲染", "AI家装", "3D设计", "3D渲染", "BIM",
    "VR家装", "VR样板间", "CAD", "参数化设计", "数字化",
    "设计软件", "设计工具", "设计平台", "云设计",
    "前后端一体", "门店管理", "量房", "效果图",
    # 行业信号
    "精装房", "毛坯房", "存量房", "二手房翻新", "旧房改造", "老房改造",
    "数字化转型", "智能家居", "智能制造", "工业4.0", "柔性制造",
    "家居展", "建博会", "家博会", "设计周",
    # 上下游
    "房地产", "楼市", "房价", "地产", "物业", "交房",
    "供应链", "板材", "五金", "配件", "封边",
    # 用户场景
    "装修日记", "装修攻略", "装修避坑", "装修预算",
    "小户型", "大平层", "别墅", "复式", "loft",
    "北欧风", "现代简约", "新中式", "美式", "法式", "侘寂",
    "厨房设计", "卫生间设计", "客厅设计", "卧室设计", "阳台设计",
    "好好住", "住小帮", "土巴兔", "齐家网", "一兜糖",
]

INDUSTRY_KW_LOWER = [kw.lower() for kw in INDUSTRY_KEYWORDS]


def is_relevant(text: str) -> bool:
    """判断文本是否与家居建材行业相关"""
    if not text:
        return False
    t = text.lower()
    return any(kw in t for kw in INDUSTRY_KW_LOWER)


# ====== 缓存 ======
_cache: dict = {}
CACHE_TTL = 600


def cached(key):
    if key in _cache and time.time() - _cache[key]["t"] < CACHE_TTL:
        return _cache[key]["d"]
    return None


def cache_set(key, data):
    _cache[key] = {"d": data, "t": time.time()}


# ====== 各平台采集 ======

async def fetch_toutiao():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc", headers={"User-Agent": UA})
        items = []
        for e in r.json().get("data", []):
            items.append({"title": e.get("Title", ""), "url": e.get("Url", ""), "hot": e.get("HotValue", 0), "source": "toutiao"})
        return items


async def fetch_weibo():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://weibo.com/ajax/side/hotSearch", headers={"User-Agent": UA, "Referer": "https://weibo.com/"})
        items = []
        for e in r.json().get("data", {}).get("realtime", []):
            w = e.get("word", "")
            items.append({"title": w, "url": f"https://s.weibo.com/weibo?q={w}", "hot": e.get("raw_hot", 0), "label": e.get("label_name", ""), "source": "weibo"})
        return items


async def fetch_zhihu():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://api.zhihu.com/topstory/hot-lists/total?limit=50", headers={"User-Agent": UA})
        items = []
        for e in r.json().get("data", []):
            t = e.get("target", {})
            items.append({"title": t.get("title", ""), "url": f"https://www.zhihu.com/question/{t.get('id', '')}", "excerpt": (t.get("excerpt", "") or "")[:200], "hot": e.get("detail_text", ""), "source": "zhihu"})
        return items


async def fetch_baidu():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://top.baidu.com/board?tab=realtime", headers={"User-Agent": UA})
        html = r.text
        m = re.search(r"<!--s-data:(.*?)-->", html, re.DOTALL)
        items = []
        if m:
            d = json.loads(m.group(1))
            for card in d.get("data", {}).get("cards", []):
                for ct in card.get("content", []):
                    items.append({"title": ct.get("word", ""), "url": ct.get("url", ""), "desc": (ct.get("desc", "") or "")[:200], "hot": ct.get("hotScore", 0), "source": "baidu"})
        return items


async def fetch_bilibili():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://api.bilibili.com/x/web-interface/popular?ps=50&pn=1", headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
        d = r.json()
        items = []
        if d.get("code") == 0:
            for v in d.get("data", {}).get("list", []):
                s = v.get("stat", {})
                items.append({"title": v.get("title", ""), "url": v.get("short_link_v2", "") or f"https://www.bilibili.com/video/{v.get('bvid', '')}", "owner": v.get("owner", {}).get("name", ""), "view": s.get("view", 0), "like": s.get("like", 0), "danmaku": s.get("danmaku", 0), "source": "bilibili"})
        return items


async def fetch_douyin():
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
        items = []
        for w in r.json().get("data", {}).get("word_list", []):
            items.append({"title": w.get("word", ""), "url": f"https://www.douyin.com/search/{w.get('word', '')}", "hot": w.get("hot_value", 0), "source": "douyin"})
        return items


async def fetch_sspai():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://sspai.com/api/v1/article/tag/page/get?limit=20&offset=0&tag=%E7%83%AD%E9%97%A8%E6%96%87%E7%AB%A0")
        items = []
        for a in r.json().get("data", []):
            items.append({"title": a.get("title", ""), "url": f"https://sspai.com/post/{a.get('id', '')}", "summary": (a.get("summary", "") or "")[:200], "likes": a.get("like_count", 0), "source": "sspai"})
        return items


async def fetch_36kr():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://36kr.com/api/newsflash?per_page=30", headers={"User-Agent": UA})
        items = []
        for n in r.json().get("data", {}).get("items", []):
            items.append({"title": n.get("title", ""), "url": n.get("news_url", f"https://36kr.com/newsflashes/{n.get('id', '')}"), "desc": (n.get("description", "") or "")[:200], "source": "36kr", "time": n.get("published_at", "")})
        return items


# ====== API 端点 ======

@app.get("/api/toutiao")
async def api_toutiao():
    c = cached("toutiao")
    if c: return c
    items = await fetch_toutiao()
    r = {"code": 0, "data": items, "total": len(items)}
    cache_set("toutiao", r)
    return r


@app.get("/api/weibo")
async def api_weibo():
    c = cached("weibo")
    if c: return c
    items = await fetch_weibo()
    r = {"code": 0, "data": items, "total": len(items)}
    cache_set("weibo", r)
    return r


@app.get("/api/zhihu")
async def api_zhihu():
    c = cached("zhihu")
    if c: return c
    items = await fetch_zhihu()
    r = {"code": 0, "data": items, "total": len(items)}
    cache_set("zhihu", r)
    return r


@app.get("/api/baidu")
async def api_baidu():
    c = cached("baidu")
    if c: return c
    items = await fetch_baidu()
    r = {"code": 0, "data": items, "total": len(items)}
    cache_set("baidu", r)
    return r


@app.get("/api/bilibili")
async def api_bilibili():
    c = cached("bilibili")
    if c: return c
    items = await fetch_bilibili()
    r = {"code": 0, "data": items, "total": len(items)}
    cache_set("bilibili", r)
    return r


@app.get("/api/douyin")
async def api_douyin():
    c = cached("douyin")
    if c: return c
    items = await fetch_douyin()
    r = {"code": 0, "data": items, "total": len(items)}
    cache_set("douyin", r)
    return r


@app.get("/api/sspai")
async def api_sspai():
    c = cached("sspai")
    if c: return c
    items = await fetch_sspai()
    r = {"code": 0, "data": items, "total": len(items)}
    cache_set("sspai", r)
    return r


@app.get("/api/36kr")
async def api_36kr():
    c = cached("36kr")
    if c: return c
    items = await fetch_36kr()
    r = {"code": 0, "data": items, "total": len(items)}
    cache_set("36kr", r)
    return r


@app.get("/api/all")
async def api_all(filter: str = Query("industry", description="industry=只保留行业相关, all=全量")):
    cache_key = f"all_{filter}"
    c = cached(cache_key)
    if c: return c

    fetchers = [
        ("toutiao", fetch_toutiao),
        ("weibo", fetch_weibo),
        ("zhihu", fetch_zhihu),
        ("baidu", fetch_baidu),
        ("bilibili", fetch_bilibili),
        ("douyin", fetch_douyin),
        ("sspai", fetch_sspai),
        ("36kr", fetch_36kr),
    ]

    results = await asyncio.gather(*[f() for _, f in fetchers], return_exceptions=True)

    all_items = []
    report_raw = {}
    report_filtered = {}

    for i, (name, _) in enumerate(fetchers):
        r = results[i]
        if isinstance(r, Exception):
            report_raw[name] = f"error: {str(r)[:80]}"
            report_filtered[name] = 0
            continue
        if not isinstance(r, list):
            report_raw[name] = 0
            report_filtered[name] = 0
            continue

        report_raw[name] = len(r)

        if filter == "industry":
            # 行业过滤: 保留标题/描述中包含行业关键词的条目
            relevant = [item for item in r if is_relevant(item.get("title", "") + " " + item.get("desc", "") + " " + item.get("excerpt", "") + " " + item.get("summary", ""))]
            # 标记相关性
            for item in relevant:
                item["relevant"] = True
            all_items.extend(relevant)
            report_filtered[name] = len(relevant)
        else:
            all_items.extend(r)
            report_filtered[name] = len(r)

    result = {
        "code": 0,
        "data": all_items,
        "total": len(all_items),
        "report_raw": report_raw,
        "report_filtered": report_filtered,
        "filter": filter,
        "timestamp": datetime.now().isoformat(),
    }
    cache_set(cache_key, result)
    return result


@app.get("/api/health")
async def health():
    return {"status": "ok", "ts": datetime.now().isoformat()}
