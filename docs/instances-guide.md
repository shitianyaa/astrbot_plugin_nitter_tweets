# Nitter 实例配置指南

本文档说明自建 Nitter 的接入方式、容器网络拓扑和实例轮换。插件不再提供公共 Nitter 默认实例；请先部署自己控制的 Nitter，再配置地址。

- 返回 [README](../README.md)
- 查看 [进阶说明](./advanced.md)

## 统一实例配置

自建 Nitter 通常同时提供 RSS 和 HTML，因此插件只保留一份实例列表：`instances`。

| 场景 | 接口 | 路径 | 配置 |
| --- | --- | --- | --- |
| 博主订阅 | RSS | `/username/rss` | `instances` |
| 标签、List、手动搜索 | HTML | `/search?...` 或 List 路径 | `instances` |

同一实例同时用于用户 RSS、用户 HTML、搜索、List 和后台并发抓取。可以填写多个自建实例，插件会按成功率、冷却状态和配置顺序轮换。

关注对象较多时，优先在 Nitter 中建立一个 List，再订阅 List 分组。这样后台可以按 List 时间线抓取，减少逐个请求用户页面的次数，更不容易触发自建实例的 429；RSS 和 HTML 共用 `retry_attempts`、`retry_delay_seconds` 重试配置。

## 容器和主机地址

| 部署拓扑 | `instances` 示例 | 说明 |
| --- | --- | --- |
| AstrBot 与 Nitter 在同一 Docker network | `http://nitter:8080` | `nitter` 是 Docker Compose 服务名 |
| AstrBot 在容器，Nitter 在宿主机 | `http://host.docker.internal:8080` | Linux 需要配置 `host-gateway`，或使用宿主机网关地址 |
| AstrBot 与 Nitter 都是宿主机进程 | `http://127.0.0.1:8080` | 两个进程确实运行在同一台主机 |
| Nitter 在另一台服务器 | `http://公网IP:8080` 或 HTTPS 域名 | 确保安全组、防火墙和反向代理允许访问 |
| 两个容器不在同一 network | 使用映射端口、宿主机地址或共享 network | 不能直接填写 `http://nitter:8080` |

AstrBot 容器内的 `127.0.0.1` 只代表 AstrBot 容器本身，不代表宿主机或 Nitter 容器。不要填写 Redis 地址，插件只需要 Nitter 的 HTTP 服务地址。

插件不再区分公网、私网或容器地址，也没有额外放行开关。只要 URL 是合法的 HTTP(S)，请求和重定向就可以访问；实例返回的媒体 URL 也会由插件下载。因此只应填写你自己控制且信任的 Nitter，并在网络层隔离 Redis、AstrBot/NapCat 管理端口、云 metadata 等内部服务。

示例：

```json
{
  "instances": ["http://nitter:8080"]
}
```

## 公共实例清理

插件不再内置或推荐 `nitter.net`、tiekoetter、Poast、kareem 等公共实例。升级后旧配置不会被迁移、覆盖或删除；请手动把旧公共地址改为自建地址。

旧版 `search_instances`、`blogger_html_instances` 和 `concurrent_fetch_instances` 已删除。插件不会读取、迁移或写回这些字段；启动日志会列出被忽略的旧实例 origin，用户需要手动整理到 `instances`。

## 用户时间线协议

用户时间线固定先请求 RSS；RSS 失败或没有结果时，自动使用同一实例列表请求 HTML 用户页。该行为不再提供开关，也不存在独立 HTML 实例池。

## 健康检查

使用 Dashboard 的“实例能力诊断”一次检查用户 RSS、用户 HTML、搜索和可选 List。管理员命令 `/镜像测试` 可临时检查单个实例的用户时间线。建议确认：

- 容器内 DNS 能否解析 Docker 服务名；
- 端口是否在 Nitter 容器监听并对 AstrBot 网络开放；
- RSS 用户页是否返回有效 XML；
- HTML 搜索是否返回时间线内容；
- 反向代理是否要求额外认证或拦截请求。

自建实例的认证、反向代理和安全组策略应在部署层配置。插件不包含公共实例挑战解算或过盾逻辑。

## 常见错误

| 错误 | 原因 | 处理 |
| --- | --- | --- |
| `未配置 Nitter 实例` | `instances` 为空 | 填写自建 Nitter 地址 |
| `无法解析 host nitter` | AstrBot 与 Nitter 不在同一 Docker network | 共享 network 或改用映射地址 |
| `连接 127.0.0.1 失败` | 127.0.0.1 指向了错误的容器 | 使用 `nitter`、`host.docker.internal` 或公网地址 |
| RSS 成功但搜索为空 | Nitter/反向代理未提供 HTML 搜索 | 检查自建 Nitter 版本和代理配置 |
| 返回登录、维护或挑战页 | 实例自身访问控制或部署异常 | 在 Nitter/反向代理层处理 |
