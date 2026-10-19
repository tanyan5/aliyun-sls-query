# -*- coding: utf-8 -*-
"""按关键字 / URI 在指定 logstore 检索日志，支持按 traceId 追链路。
用法:
  python sls_search.py <logstore> <query> <hours> [max_lines]
  python sls_search.py <module>-backend delOrder 24
  python sls_search.py <module>-backend "routineOrder/delOrder" 24 50
"""
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
require_target(project=PROJECT, endpoint=ENDPOINT)


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


RE_TID = re.compile(r'\[(\S{8,})\s+(\S{8,})\]')
RE_OP  = re.compile(r'操作人\s*=\s*(\S+)')
RE_IP  = re.compile(r'IP\s*=\s*(\S+)')
RE_URI = re.compile(r'RUI\s*=\s*\[([^\]]*)\]')


def endpoint_of(content):
    """按 RUI 中的 /app/ 判定 PC 还是 APP 端（坑 F）"""
    m = RE_URI.search(content or "")
    if not m:
        return "?"
    return "APP" if "/app/" in m.group(1) else "PC"


def operator_of(content):
    m = RE_OP.search(content or "")
    return m.group(1) if m else "?"


def tstr(r):
    ts = r.get("__time__")
    return time.strftime("%m-%d %H:%M:%S", time.localtime(int(ts))) if ts else "?"


if __name__ == "__main__":
    logstore = sys.argv[1] if len(sys.argv) > 1 else _defaults.get("logstore", "<module>-backend")
    require_target(logstore=logstore)
    query = sys.argv[2] if len(sys.argv) > 2 else "delOrder"
    hours = int(sys.argv[3]) if len(sys.argv) > 3 else 24
    max_lines = int(sys.argv[4]) if len(sys.argv) > 4 else 100

    now = int(time.time())
    frm, to = now - hours * 3600, now
    print("Logstore: %s | 窗口: %s ~ %s (近 %d 小时)" % (
        logstore,
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(frm)),
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(to)), hours))

    recs = fetch_all(logstore, query, frm, to, max_lines=max_lines)
    print("命中: %d 条" % len(recs))
    for i, r in enumerate(recs):
        c = r.get("content", "")
        tid = "?"
        m = RE_TID.search(c)
        if m:
            tid = m.group(1)
        u = RE_URI.search(c)
        uri = u.group(1) if u else "-"
        pod = r.get("__tag__:_pod_name_", "?")
        op = operator_of(c)
        ep = endpoint_of(c)
        print("\n[%d] %s pod=%s trace=%s endpoint=%s operator=%s uri=%s" % (
            i, tstr(r), pod, tid, ep, op, uri))
        print("    " + c[:300].replace("\n", " "))
