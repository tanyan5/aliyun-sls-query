# -*- coding: utf-8 -*-
"""找今天最新的 /inc/dataCenter/syncStoreEstQuantity 请求，并定位 1200002156 的入参 est* 字段。"""
import sys, json, time, hmac, hashlib, base64, urllib.parse, urllib.request, urllib.error, re
from email.utils import formatdate

sys.stdout.reconfigure(encoding='utf-8')

import os, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sls_auth import load_credentials, load_defaults, require_target
_defaults = load_defaults()
AK, SK = load_credentials()

PROJECT  = os.environ.get("SLS_PROJECT", _defaults.get("project", "k8s-log-<project-id>"))
ENDPOINT = os.environ.get("SLS_ENDPOINT", _defaults.get("endpoint", "cn-hangzhou.log.aliyuncs.com"))
LOGSTORE = os.environ.get("SLS_LOGSTORE", _defaults.get("logstore", "<module>-backend"))
require_target(PROJECT, LOGSTORE, ENDPOINT)


def sign(method, uri_path, query, headers):
    md5 = headers.get("Content-MD5", "")
    ctype = headers.get("Content-Type", "")
    sls = sorted("%s:%s\n" % (k.lower(), v.strip())
                 for k, v in headers.items()
                 if k.lower().startswith(("x-log-", "x-acs-")))
    sign_str = "%s\n%s\n%s\n%s\n%s%s" % (
        method.upper(), md5, ctype, headers["Date"], "".join(sls), uri_path)
    if query:
        sign_str += "?" + "&".join(query)
    return "LOG %s:%s" % (AK, base64.b64encode(
        hmac.new(SK.encode(), sign_str.encode(), hashlib.sha1).digest()).decode())


def get_logs(query="", frm=None, to=None, line=100, offset=0, reverse=True):
    uri = "/logstores/%s" % LOGSTORE
    q = [("type", "log"), ("from", str(frm)), ("to", str(to)), ("line", str(line)),
         ("offset", str(offset)), ("reverse", "true" if reverse else "false")]
    if query:
        q.append(("query", query))
    q.sort(key=lambda x: x[0])
    sign_q = ["%s=%s" % (k, v) for k, v in q]
    host = "%s.%s" % (PROJECT, ENDPOINT)
    headers = {
        "Date": formatdate(usegmt=True),
        "Content-Type": "application/json",
        "x-log-apiversion": "0.6.0",
        "x-log-signaturemethod": "hmac-sha1",
        "x-log-bodyrawsize": "0",
        "Host": host,
    }
    headers["Authorization"] = sign("GET", uri, sign_q, headers)
    url = "http://%s%s?%s" % (host, uri, urllib.parse.urlencode(q, quote_via=urllib.parse.quote))
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def fetch_all(query, frm, to, max_lines=3000):
    out = []
    offset = 0
    while offset < max_lines:
        code, body = get_logs(query, frm=frm, to=to, line=100, offset=offset, reverse=False)
        if code != 200:
            print("HTTP %s: %s" % (code, body[:600]))
            break
        try:
            data = json.loads(body)
        except Exception:
            print("解析失败:", body[:600])
            break
        if not data:
            break
        out.extend(data)
        if len(data) < 100:
            break
        offset += len(data)
    return out


def tstr(r):
    ts = r.get("__time__")
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts))) if ts else "?"


if __name__ == "__main__":
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    merch = sys.argv[2] if len(sys.argv) > 2 else "1200002156"
    now = int(time.time())
    frm, to = now - hours * 3600, now
    print("窗口: %s ~ %s" % (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(frm)),
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(to))))

    recs = fetch_all('syncStoreEstQuantity', frm, to)
    print("syncStoreEstQuantity 命中:", len(recs))

    # 请求行：含完整 URI /inc/dataCenter/syncStoreEstQuantity
    reqs = [r for r in recs if '/inc/dataCenter/syncStoreEstQuantity' in r.get('content', '')]
    print("其中请求行(/inc/dataCenter/...):", len(reqs))
    reqs.sort(key=lambda r: int(r.get('__time__', 0)))
    if not reqs:
        print("无请求日志记录，退出")
        sys.exit(0)

    latest = reqs[-1]
    print("\n===== 最新请求 @ %s =====" % tstr(latest))
    c = latest.get('content', '')
    m = re.match(r'^\S+ \S+\s+\w+\s+\[(\S+)\s+(\S+)\]', c)
    tid = m.group(1) if m else '?'
    span = m.group(2) if m else '?'
    print("traceId=", tid, "spanId=", span)
    print("耗时:", (re.search(r'耗时 = \[(\d+)\]', c) or [None, '?'])[1])
    # 打印请求行头部(不含超长 body)
    head = c[:500]
    print("HEAD:", head)
    print("body 总长:", len(c))

    # 把完整请求日志存盘
    with open("latest_request.txt", "w", encoding="utf-8") as f:
        f.write(c)
    print("已写入 latest_request.txt")

    # 在 body 里定位该物料的入参块（含 estQuantity / estQuality 等字段）
    # 兼容 JSON 风格 / 紧凑风格
    for pat in [r'\{[^{}]*1200002156[^{}]*\}', r'"merchandiseCode"\s*:\s*"1200002156".{0,400}']:
        for mm in re.finditer(pat, c):
            seg = mm.group(0)
            print("\n--- 命中物料块 ---")
            print(seg[:700])
            # 提取 est* 字段
            for fld in re.findall(r'"(est[A-Za-z]+)"\s*:\s*("?-?\d+\.?\d*"?|null)', seg):
                print("  字段:", fld)

    # 也全局搜 estQuality / estQuantity 紧跟 1200002156 上下文
    for kw in ['estQuality', 'estQuantity']:
        idx = c.find('1200002156')
        while idx != -1:
            window = c[max(0, idx - 200): idx + 200]
            if kw in window:
                print("\n[上下文] %s 出现在 1200002156 附近:" % kw)
                print(window)
            idx = c.find('1200002156', idx + 1)

    print("\n======== traceId %s 用于下一步追链路 =====" % tid)
    with open("latest_tid.txt", "w", encoding="utf-8") as f:
        f.write(tid)
