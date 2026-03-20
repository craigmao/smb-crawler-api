# SMB 情报爬虫 API 部署指南

## 架构

```
[国内服务器]                          [Vercel]
smb-crawler-api                      smb-intel
├── /api/toutiao  (头条热榜 50条)      ├── /api/intel → 调用国内爬虫API
├── /api/weibo    (微博热搜 50条)      ├── /dashboard → 情报展示
├── /api/zhihu    (知乎热榜 30条)      └── 环境变量:
├── /api/baidu    (百度热搜 50条)          CRAWLER_API_URL=https://你的国内服务器
├── /api/bilibili (B站热门  50条)
├── /api/douyin   (抖音热搜 50条)
├── /api/sspai    (少数派   20条)
├── /api/juejin   (掘金热榜)
├── /api/36kr     (36氪快讯 30条)
├── /api/xiaohongshu (小红书, 需MediaCrawler)
└── /api/all      (全量聚合 330+条)
```

## 方案一：阿里云 ECS (推荐, 最稳定)

### 1. 购买服务器
- 阿里云 → 云服务器 ECS → 抢占式实例
- 配置: 2核4G, Ubuntu 22.04, 带公网IP
- 价格: 约 ¥30-50/月

### 2. 部署
```bash
# SSH 登录后
sudo apt update && sudo apt install -y docker.io docker-compose git

# 克隆项目
git clone https://github.com/craigmao/smb-crawler-api.git
cd smb-crawler-api

# 一键启动
docker-compose up -d

# 验证
curl http://localhost:8000/api/all | python3 -m json.tool | head -20
```

### 3. 配置 Vercel 环境变量
在 Vercel 项目设置中添加:
```
CRAWLER_API_URL = http://你的服务器IP:8000
```

## 方案二：腾讯云轻量应用服务器

### 1. 购买
- 腾讯云 → 轻量应用服务器
- 配置: 2核2G, Docker 镜像
- 价格: ¥45/月 (新用户首年 ¥50)

### 2. 部署 (同上)

## 方案三：Railway (海外, 免费额度)

Railway 有 $5/月免费额度, 但是海外服务器, 部分平台可能被墙。

```bash
# 安装 Railway CLI
npm i -g @railway/cli

# 部署
railway login
railway init
railway up
```

## 方案四：Zeabur (有新加坡/香港节点)

Zeabur 有亚太节点, 比纯美国节点好一些。

## 后续: 接入 MediaCrawler (深度采集)

当前版本使用公开热榜 API, 如需小红书笔记内容、抖音视频详情等深度数据:

```bash
# 在服务器上
cd smb-crawler-api
git clone https://github.com/NanmiCoder/MediaCrawler.git

# 安装依赖
cd MediaCrawler
pip install -r requirements.txt
playwright install chromium

# 配置 (需要扫码登录)
# 编辑 config/base_config.py
```

MediaCrawler 支持: 小红书笔记+评论+搜索 / 抖音视频+评论 / B站视频+评论 / 微博博文+评论 / 知乎问答+评论 / 百度贴吧
