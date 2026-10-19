# -*- coding: utf-8 -*-
"""定位指定门店的 syncStoreEstQuantity 请求 -> traceId -> 该链路上的 SQL 及参数

用法: python sls_trace.py [hours] <门店号>
  门店号可传裸号或带业务前缀，脚本统一按「业务前缀 1_ + 门店号」检索。
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
    return time.strftime("%m-%d %H:%M:%S", time.localtime(int(ts))) if ts else "?"


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python sls_trace.py [hours] <门店号>")
        print("  例: python sls_trace.py 24 <门店号>   或   python sls_trace.py 24 1_<门店号>")
        print("  （门店号为必填，裸号会自动补上业务前缀 1_）")
        sys.exit(1)
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    _raw_store = sys.argv[2]
    STORE = _raw_store if _raw_store.startswith("1_") else "1_" + _raw_store
    now = int(time.time())
    frm, to = now - hours * 3600, now
    print("窗口: %s ~ %s" % (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(frm)),
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(to))))

    recs = fetch_all('syncStoreEstQuantity', frm, to)
    print("syncStoreEstQuantity 命中:", len(recs))
    hits = [r for r in recs if STORE in r.get('content', '')]
    print("其中含 %s 的请求日志: %d" % (STORE, len(hits)))
    trace_ids = []
    for i, r in enumerate(hits):
        c = r.get('content', '')
        m = re.match(r'^\S+ \S+\s+\w+\s+\[(\S+)\s+(\S+)\]', c)
        tid = m.group(1) if m else '?'
        trace_ids.append(tid)
        print("\n=== 请求 [%d] %s trace=%s ===" % (i, tstr(r), tid))
        print("  storeCode 出现次数:", c.count(STORE))
        for mm in re.finditer(r'.{80}' + re.escape(STORE) + r'.{80}', c):
            print("   ...", mm.group(0))
        print("   耗时:", re.search(r'耗时 = \[(\d+)\]', c).group(1) if re.search(r'耗时 = \[(\d+)\]', c) else '?')

    print("\n\n########## traceId 列表 ##########")
    print(trace_ids)

    # 按 traceId 拉该链路全部日志
    for tid in trace_ids:
        print("\n\n########## trace=%s 链路日志 ##########" % tid)
        rs = fetch_all(tid, frm, to, max_lines=1000)
        for r in rs:
            c = r.get('content', '')
            print("\n--- %s ---" % tstr(r))
            print(c[:2500])
