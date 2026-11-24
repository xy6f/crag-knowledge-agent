# 云途 SaaS API 接入文档（摘要）

> 状态：现行（2025-09 修订）

## 鉴权
采用 AK/SK 机制：在管理后台「开发者中心」创建应用获得 AccessKey 与 SecretKey。请求头携带 `X-Yuntu-AK` 与 `X-Yuntu-Sign`（HMAC-SHA256，基于请求体 + 时间戳计算）。时间戳与服务器偏差超过 300 秒将返回 401。

## 限流
- 标准版：不开放 API
- 专业版：50 QPS / 应用
- 旗舰版：200 QPS / 应用
超限返回 HTTP 429，响应头 `Retry-After` 指示重试间隔。突发流量支持 2 倍瞬时桶（令牌桶算法）。

## 核心接口
- `GET /api/v3/customers` 客户列表（游标分页，单页最大 200）
- `POST /api/v3/opportunities` 创建商机
- `POST /api/v3/tickets` 创建工单
- `GET /api/v3/reports/daily` 日报数据

## Webhook
支持事件：customer.created、deal.stage_changed、ticket.resolved 等 18 类。推送失败自动重试 5 次（指数退避），可在后台查看投递日志。回调需在 2 秒内返回 200。

## SDK
官方 SDK：Java / Python / Go，仓库地址见开发者中心。SDK 内置签名与限流退避，推荐生产环境使用。
