# -*- coding: utf-8 -*-
"""按 traceId 拉取整条链路日志（含跨线程），本地打印全文。
用法: python sls_traceid.py <traceId> [hours] [logstore]
"""
import sys, json, time, hmac, hashlib, base64, urllib.parse, urllib.request, urllib.error, re
from email.utils import formatdate

sys.stdout.reconfigure(encoding='utf-8')

import os, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sls_auth import load_credentials
AK, SK = load_credentials()

PROJECT  = os.environ.get("SLS_PROJECT", "k8s-log-c690075cfa6764ccda7b33582e001db23")
ENDPOINT = os.environ.get("SLS_ENDPOINT", "cn-hangzhou.log.aliyuncs.com")


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


def get_logs(logstore, query="", frm=None, to=None, line=100, offset=0, reverse=True):
    uri = "/logstores/%s" % logstore
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
    url = "http://%s%s?%s" % (
        host, uri, urllib.parse.urlencode(q, quote_via=urllib.parse.quote))
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def fetch_all(logstore, query, frm, to, max_lines=3000):
    out = []
    offset = 0
    while offset < max_lines:
        code, body = get_logs(logstore, query, frm=frm, to=to, line=100, offset=offset, reverse=False)
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
    return time.strftime("%m-%d %H:%M:%S", time.localtime(int(ts))) if ts else "?"


if __name__ == "__main__":
    tid = sys.argv[1]
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 48
    logstore = sys.argv[3] if len(sys.argv) > 3 else "inc-backend"
    now = int(time.time())
    frm, to = now - hours * 3600, now
    print("Logstore: %s | traceId: %s | 窗口近 %d 小时" % (logstore, tid, hours))
    recs = fetch_all(logstore, tid, frm, to, max_lines=2000)
    print("链路日志条数: %d\n" % len(recs))
    # 按时间排序
    recs.sort(key=lambda r: int(r.get("__time__", 0)))
    for r in recs:
        print("[%s] %s" % (tstr(r), r.get("content", "")))
