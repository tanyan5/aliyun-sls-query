# -*- coding: utf-8 -*-
"""阿里云 SLS 查询 inc-backend 近 15 分钟日志"""
import sys, json, time, hmac, hashlib, base64, urllib.parse, urllib.request, urllib.error
from email.utils import formatdate

sys.stdout.reconfigure(encoding='utf-8')

import os, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sls_auth import load_credentials
AK, SK = load_credentials()

PROJECT  = os.environ.get("SLS_PROJECT", "k8s-log-c690075cfa6764ccda7b33582e001db23")
ENDPOINT = os.environ.get("SLS_ENDPOINT", "cn-hangzhou.log.aliyuncs.com")
LOGSTORE = os.environ.get("SLS_LOGSTORE", "inc-backend")


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


def get_logs(query="", frm=None, to=None, line=10, offset=0, reverse=True, power_sql=False):
    now = int(time.time())
    frm = frm if frm is not None else now - 900
    to = to if to is not None else now
    uri = "/logstores/%s" % LOGSTORE
    q = [("type", "log"), ("from", str(frm)), ("to", str(to)), ("line", str(line)),
         ("offset", str(offset)), ("reverse", "true" if reverse else "false")]
    if power_sql:
        q.append(("powerSql", "true"))
    if query:
        q.append(("query", query))
    q.sort(key=lambda x: x[0])
    # 签名串使用原始值
    sign_q = ["%s=%s" % (k, v) for k, v in q]
    # URL 只编码 value，保留 key=value 结构
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
        host, uri,
        urllib.parse.urlencode(q, quote_via=urllib.parse.quote))
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


SQLS = {
    "uri": r"""* | select regexp_extract(content, 'RUI = \[([^\]]*)\]', 1) as uri, count(*) as cnt group by uri order by cnt desc limit 60""",
    "api": r"""* | select regexp_extract(content, '\[inc\]-\[([^\]]*)\]', 1) as api, count(*) as cnt group by api order by cnt desc limit 40""",
    "level": r"""* | select regexp_extract(content, '^\d{4}-\d{2}-\d{2} \S+ (ERROR|WARN|INFO|DEBUG)', 1) as lvl, count(*) as cnt group by lvl order by cnt desc""",
    "slow": r"""* | select regexp_extract(content, 'RUI = \[([^\]]*)\]', 1) as uri, max(cast(regexp_extract(content, '耗时 = \[(\d+)\]', 1) as bigint)) as max_ms, avg(cast(regexp_extract(content, '耗时 = \[(\d+)\]', 1) as bigint)) as avg_ms, count(*) as cnt group by uri having max_ms is not null order by max_ms desc limit 15""",
    "err": r"""ERROR | select content order by __time__ desc limit 20""",
}


def run(mode="analyze"):
    import time as _t
    now = int(_t.time())
    print("时间窗口: %s ~ %s (近15分钟, 本地时间 GMT+8)" % (
        _t.strftime("%H:%M:%S", _t.localtime(now - 900)),
        _t.strftime("%H:%M:%S", _t.localtime(now))))
    for name, q in SQLS.items():
        if mode != "analyze" and mode != name:
            continue
        code, body = get_logs(q, line=100)
        print("\n===== %s (code=%s) =====" % (name, code))
        try:
            data = json.loads(body)
            if name == "err":
                for r in data[:15]:
                    print(" ", r.get("content", "")[:200])
            else:
                for r in data:
                    print("  " + json.dumps(r, ensure_ascii=False))
        except Exception:
            print(body[:1500])


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sample"
    if mode == "analyze" or mode in SQLS:
        run(mode)
    elif mode == "sample":
        code, body = get_logs("", line=5)
        print("code=", code)
        try:
            data = json.loads(body)
            print("count=", len(data))
            for i, rec in enumerate(data[:5]):
                print("\n--- record %d ---" % i)
                print(json.dumps(rec, ensure_ascii=False)[:1500])
        except Exception:
            print(body[:2000])
    else:
        q = sys.argv[2]
        code, body = get_logs(q, line=100, power_sql=True)
        print("code=", code)
        print(body[:6000])
