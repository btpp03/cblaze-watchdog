#!/usr/bin/env python3
"""
CloudBlaze 免费游戏服看门狗（btppcn / cb521bab）。

作用：这台免费实例上寄生着 hy2 节点 + 哪吒 v1（都在 MC 的 JVM 里），
MC 一停 = 节点和探针全断。免费节点维护后不会自动拉起来，所以每 6 小时：

  1. 探测 MC 端口（TCP 10446）是否活着
  2. 用面板 API 查 state（cookie 会话，需 CBLZ_COOKIES secret）
  3. state 不是 running 或端口死 -> POST /power {"signal":"start"}
  4. 需要动手时才推 Telegram，正常静默

环境变量：
  CBLZ_COOKIES   必需。panel.cloudblaze.org 的 cookie JSON 数组
                 (name/value/domain/path/secure/expires)，含 remember_web + XSRF-TOKEN + __ddg*
  CBLZ_SID       可选。服务器标识，默认 cb521bab
  CBLZ_HOST/PORT 可选。默认 free.cloudblaze.org:10446
  TG_BOT_TOKEN / TG_CHAT_ID  可选。告警推送
"""
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpc  # axelot __BPC 挑战求解器（同目录）

PANEL = "https://panel.cloudblaze.org"
SID = os.environ.get("CBLZ_SID", "cb521bab").strip()
HOST = os.environ.get("CBLZ_HOST", "free.cloudblaze.org").strip()
PORT = int(os.environ.get("CBLZ_PORT", "10446"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
BJ = timezone(timedelta(hours=8))


def log(*a):
    print(datetime.now(BJ).strftime("%H:%M:%S"), *a, flush=True)


def tg(text):
    tok = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat = os.environ.get("TG_CHAT_ID", "").strip()
    if not tok or not chat:
        return
    data = json.dumps({"chat_id": chat, "text": text,
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                 data=data, headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        urllib.request.urlopen(req, timeout=20)
        log("telegram notified")
    except Exception as e:
        log("telegram failed:", e)


def build_opener():
    raw = os.environ.get("CBLZ_COOKIES", "").strip()
    if not raw:
        print("FATAL: 未配置 CBLZ_COOKIES", file=sys.stderr)
        sys.exit(2)
    cookies = json.loads(raw)
    cj = http.cookiejar.CookieJar()
    xsrf = ""
    for c in cookies:
        # 只留登录态；__bp_* / __ddg* 是 IP+时效绑定的，带旧的一起发反而会被判无效
        # 让请求重新触发挑战，由 bpc.solve() 现拿一份新的
        if c["name"].startswith(("__bp", "__ddg")):
            continue
        dom = c["domain"]
        if not dom.startswith("."):
            dom = "." + dom
        exp = c.get("expires", -1)
        cj.set_cookie(http.cookiejar.Cookie(
            version=0, name=c["name"], value=c["value"], port=None, port_specified=False,
            domain=dom, domain_specified=True, domain_initial_dot=True,
            path=c.get("path", "/"), path_specified=True,
            secure=bool(c.get("secure", True)),
            expires=int(exp) if exp and exp > 0 else None,
            discard=False, comment=None, comment_url=None, rest={}, rfc2109=False))
        if c["name"] == "XSRF-TOKEN":
            xsrf = c["value"]
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj)), xsrf


def api(op, xsrf, path, method="GET", body=None):
    code, txt = _api_raw(op, xsrf, path, method, body)
    if code == 403 and "__BPC" in txt:
        # 走了没被放行的出口 IP（比如 GitHub runner）会先撞上 axelot 的
        # 指纹 + PoW 挑战页；解掉拿 __bp_verified，再重放原请求
        log("hit bot challenge, solving...")
        bpc.solve(op, PANEL, path)
        code, txt = _api_raw(op, xsrf, path, method, body)
    return code, txt


def _api_raw(op, xsrf, path, method="GET", body=None):
    req = urllib.request.Request(PANEL + path, data=body, method=method)
    req.add_header("User-Agent", bpc.UA)
    req.add_header("Accept", "application/json")
    req.add_header("X-Requested-With", "XMLHttpRequest")
    if body is not None:
        req.add_header("Content-Type", "application/json")
        # XSRF cookie 是 URL-encoded 的，必须解码后再放 header，否则 419
        req.add_header("X-XSRF-TOKEN", urllib.parse.unquote(xsrf))
    try:
        with op.open(req, timeout=45) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def mc_alive():
    try:
        s = socket.create_connection((HOST, PORT), timeout=12)
        s.close()
        return True
    except Exception as e:
        log("tcp probe failed:", e)
        return False


def state_of(op, xsrf):
    code, txt = api(op, xsrf, f"/api/client/servers/{SID}/resources")
    if code == 200:
        a = json.loads(txt)["attributes"]
        return a.get("current_state"), a.get("resources", {}).get("memory_bytes"), code, txt
    return None, None, code, txt


def main():
    op, xsrf = build_opener()
    st, mem, code, txt = state_of(op, xsrf)

    if code != 200:
        # 会话失效(401/403/419) 或面板抽风：cookie 需要换新
        msg = (f"⚠️ CloudBlaze 看门狗：面板 API 返回 HTTP {code}，会话可能失效，"
               f"需要换 CBLZ_COOKIES。这期间不会自动拉起。\n{txt[:150]}")
        log("panel api failed", code, txt[:150])
        tg(msg)
        print(f"::warning::panel api {code}")
        return 4

    alive = mc_alive()
    log(f"panel state={st} mem={mem} | mc_port={'up' if alive else 'DOWN'}")

    if st == "running" and alive:
        log("OK 无需动作")
        print(f"result: ok state=running mc=up mem={mem}")
        return 0

    if st == "running" and not alive:
        # 可能在重启中，再等一轮
        log("state=running 但端口不通，等 60s 复查")
        time.sleep(60)
        alive = mc_alive()
        if alive:
            log("恢复，无需动作")
            print("result: ok recovered")
            return 0

    log(f"动作: 拉起 (原 state={st} mem={mem})")

    # 僵死判定：state=starting 但内存为 0 = 容器没真起来（wings 卡住）。
    # 这时单发 start 只会一直 204 + starting，必须 kill 后重开。
    wedged = (st == "starting" and not mem)
    if st == "starting" and not wedged:
        # 正常启动中（有内存），先等它自己起完
        for _ in range(8):
            time.sleep(15)
            st2, mem2, _, _ = state_of(op, xsrf)
            if st2 == "running" and mc_alive():
                log("本来就在启动中，已就绪")
                print("result: ok recovered")
                return 0
        wedged = True

    def power(sig):
        c, t = api(op, xsrf, f"/api/client/servers/{SID}/power",
                   method="POST", body=json.dumps({"signal": sig}).encode())
        log(f"power {sig} ->", c, t[:80])
        return c

    for attempt in (1, 2):
        if wedged or attempt == 2:
            power("kill")
            time.sleep(10)
        power("start")
        for i in range(14):  # 单轮最多等 3.5 分钟
            time.sleep(15)
            st2, mem2, _, _ = state_of(op, xsrf)
            al = mc_alive()
            log(f"attempt{attempt} check {i + 1}: state={st2} mem={mem2} mc={'up' if al else 'down'}")
            if st2 == "running" and al:
                tg(f"🔧 CloudBlaze 看门狗：免费服被停了（原 state={st}），已自动拉起 ✅\n"
                   f"MC ping 正常，hy2/哪吒随之恢复。")
                print("result: restarted ok")
                return 0
            if st2 == "starting" and not mem2:
                wedged = True  # 这一轮又僵死了，下一轮改 kill+start
                break

    tg(f"❌ CloudBlaze 看门狗：免费服被停了且自动拉起失败（原 state={st}），请去面板手动点启动。")
    print("::error::restart failed after 2 attempts")
    return 5


if __name__ == "__main__":
    sys.exit(main())
