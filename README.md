# cblaze-watchdog

CloudBlaze 免费 Minecraft 实例（`btppcn` / `cb521bab`）的看门狗。

## 为什么需要

这台免费服上寄生着两个东西：**hy2 代理节点**和**哪吒 v1 探针**，都在 MC 的 JVM 插件里。
所以服务器一停 = 节点断 + 探针离线。免费节点维护或进程崩了之后不会自己回来，得有人去面板点启动。

## 做什么

每 6 小时（cron-job.org 外部触发）：

1. TCP 探 `free.cloudblaze.org:10446` 是否活着
2. 走面板 API 查 `current_state`
3. 只要不是 `running` 或者端口不通 → `POST /power {"signal":"start"}`
4. 起来后复查，需要动手时才推 Telegram；一切正常就静默

## 关键接口（踩过的坑）

```
POST https://panel.cloudblaze.org/api/client/servers/cb521bab/power
Content-Type: application/json
X-XSRF-TOKEN: <cookie 里 XSRF-TOKEN 的 URL 解码值>
body: {"signal":"start"}      -> 204
```

- 字段名是 `signal`，不是 `action`（传 `action` 会 422 "signal field is required"）
- `XSRF-TOKEN` cookie 是 URL-encoded 的，不 `unquote` 直接塞 header 会 **419 CSRF mismatch**
- 站点侧 `api.cloudblaze.org/servers/{id}/action` 恒 500，别用
- 面板 `panel.cloudblaze.org` 有 DDoS-Guard + 指纹校验，纯 HTTP 直接登录是 403
  「Checking your browser」；所以这里复用一份已登录的 cookie 会话
- `GET /api/client/servers/{id}/resources` 用同一份 cookie 可直接读，无需 websocket

## 配置

Secrets（仓库 Settings → Secrets and variables → Actions）：

- `CBLZ_COOKIES` 必需 — `panel.cloudblaze.org` 的 cookie JSON 数组（含 `remember_web_*`、`XSRF-TOKEN`、`__ddg*`、`pterodactyl_session`）
- `TG_BOT_TOKEN` / `TG_CHAT_ID` 可选 — 告警推送

可选环境变量：`CBLZ_SID`（默认 `cb521bab`）、`CBLZ_HOST`、`CBLZ_PORT`。

## cookie 会过期

`remember_web_*` 是 Laravel 记住登录 token，通常能撑很久；一旦面板会话失效，
Action 会失败并推送「需要换 CBLZ_COOKIES」的告警。换法：
浏览器登录面板 → 导出 cookie JSON → `gh secret set CBLZ_COOKIES -R btpp03/cblaze-watchdog < cblz_cookies.json`。

## 到期提醒

免费档 `autoRenew=false`，**北京时间 2026-12-02 11:10 到期**，一次性免费，无法续期，只能重新下单。
到期后本看门狗会一直告警，届时直接停用它。

## 本地手动跑

```bash
CBLZ_COOKIES="$(cat cblz_cookies.json)" python3 watch.py
```
