"""axelot.net __BPC 挑战求解器（纯 stdlib）。

流程：任意请求被 403 + `window.__BPC={sid,non,dif,ts}` 拦下时
  commit = sha256(cf|wv|wr|ff|af|pl|tz|sw|sh|cd|hc)
  pow    = 找 n 使 sha256(sid:non:commit:n) 以 dif 个 '0' 开头
  POST /__bp_verify  -> 服务端下发 __bp_verified / __bp_session cookie
之后带 cookie 重新请求即可。注意 navigator.webdriver 为真会被判 bot，所以别用 Playwright 默认指纹。
"""
import hashlib
import json
import re
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _numhash(s: str) -> str:
    """复刻页面里的 ((hash<<5)-hash)+char 32 位有符号循环。"""
    h = 0
    for ch in s:
        h = ((h << 5) - h) + ord(ch)
        h &= 0xFFFFFFFF
        if h >= 0x80000000:
            h -= 0x100000000
    return format(abs(h), "x")


FP = {
    "sw": "1920", "sh": "1080", "aw": "1920", "ah": "1040",
    "cd": "24", "pr": "1",
    "wv": "Google Inc. (Intel)",
    "wr": "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "pl": "Win32", "hc": "8", "dm": "8", "mt": "0",
    "tz": "Asia/Shanghai", "to": "-480", "ln": "zh-CN,zh,en",
    "ss": "1", "ls": "1", "id": "1", "wg": "1", "ck": "1", "dn": "",
    "hp": "1", "pc": "5", "cr": "1", "pm": "1",
    "wd": "0", "ph": "0", "nm": "0", "se": "0", "pp": "0", "pw": "0",
    "hl": "0", "ct": "1", "nc": "0", "bp": "0", "nl": "0", "mb": "0",
    "cf": _numhash("axelot-canvas-fp"), "ff": _numhash("Arial,Helvetica,Times"),
    "af": _numhash("audio-fp"),
}

COMMIT_FIELDS = ["cf", "wv", "wr", "ff", "af", "pl", "tz", "sw", "sh", "cd", "hc"]


def _open(op, url, data=None, headers=None, timeout=45):
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8")
    req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with op.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def solve(op, base: str, path: str = "/", max_rounds: int = 3):
    """确保能拿到正常内容；返回 (status, body)。自动解 __BPC 挑战。"""
    url = base.rstrip("/") + path
    for _ in range(max_rounds):
        code, body = _open(op, url)
        m = re.search(r"__BPC=\{sid:'([0-9a-f]+)',non:'([0-9a-f]+)',dif:(\d+),ts:(\d+)\}", body)
        if code == 200 or not m:
            return code, body
        sid, non, dif = m.group(1), m.group(2), int(m.group(3))
        t0 = time.time()
        commit = sha256_hex("|".join(str(FP[f]) for f in COMMIT_FIELDS))
        n = 0
        prefix = "0" * dif
        while True:
            if sha256_hex(f"{sid}:{non}:{commit}:{n}").startswith(prefix):
                break
            n += 1
        payload = dict(FP)
        payload.update({
            "sid": sid, "pow": sha256_hex(f"{sid}:{non}:{commit}:{n}"), "pn": str(n),
            "et": str(max(1200, int((time.time() - t0) * 1000))),
            "tm": "1", "oe": "0", "tp": "0",
        })
        vc, vb = _open(op, base.rstrip("/") + "/__bp_verify", data=json.dumps(payload).encode(),
                       headers={"Content-Type": "application/json", "Origin": base.rstrip("/"),
                                "Referer": url})
        print(f"[bpc] solved dif={dif} n={n} verify={vc} {vb[:120]}")
        if vc not in (200, 201, 204):
            time.sleep(1)
    return _open(op, url)
