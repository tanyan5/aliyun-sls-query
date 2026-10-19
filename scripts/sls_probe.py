# -*- coding: utf-8 -*-
"""阿里云 SLS 查询：探测 project 所在 region 与 logstore 列表（纯标准库实现签名）"""
import sys, os, json, hmac, hashlib, base64, urllib.request, urllib.error
from email.utils import formatdate

sys.stdout.reconfigure(encoding='utf-8')

import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sls_auth import load_credentials, load_defaults
_defaults = load_defaults()
AK, SK = load_credentials()

PROJECT = os.environ.get("SLS_PROJECT", _defaults.get("project", "k8s-log-<project-id>"))

REGIONS = [
    "cn-hangzhou", "cn-beijing", "cn-shanghai", "cn-shenzhen", "cn-guangzhou",
    "cn-qingdao", "cn-zhangjiakou", "cn-huhehaote", "cn-wulanchabu", "cn-chengdu",
    "cn-nanjing", "cn-fuzhou", "cn-wuhan-lr", "cn-hongkong",
    "ap-southeast-1", "ap-southeast-2", "ap-southeast-3", "ap-southeast-5",
    "ap-southeast-6", "ap-southeast-7", "ap-northeast-1", "ap-northeast-2",
    "ap-south-1", "us-west-1", "us-east-1", "eu-west-1", "eu-central-1",
    "cn-hangzhou-finance", "cn-shanghai-finance-1", "cn-shenzhen-finance-1",
    "cn-beijing-finance-1", "cn-hangzhou-boe", "cn-beijing-nmg",
]


def sign(method, uri_path, query, headers, body=b""):
    """SLS 经典签名: LOG <ak>:<base64(hmac-sha1)>"""
    md5 = headers.get("Content-MD5", "")
    ctype = headers.get("Content-Type", "")
    date = headers["Date"]
    sls_headers = []
    for k, v in headers.items():
        lk = k.lower()
        if lk.startswith("x-log-") or lk.startswith("x-acs-"):
            sls_headers.append("%s:%s\n" % (lk, v.strip()))
    sls_headers.sort()
    sign_str = "%s\n%s\n%s\n%s\n%s%s" % (
        method.upper(), md5, ctype, date, "".join(sls_headers), uri_path
    )
    if query:
        sign_str += "?" + "&".join(query)
    sig = base64.b64encode(
        hmac.new(SK.encode(), sign_str.encode(), hashlib.sha1).digest()
    ).decode()
    return "LOG %s:%s" % (AK, sig)


def request(endpoint, method, uri_path, query=None, project=True, timeout=20):
    query = query or []
    host = ("%s.%s" % (PROJECT, endpoint)) if project else endpoint
    url = "http://%s%s" % (host, uri_path)
    if query:
        url += "?" + "&".join(query)
    headers = {
        "Date": formatdate(usegmt=True),
        "Content-Type": "application/json",
        "x-log-apiversion": "0.6.0",
        "x-log-signaturemethod": "hmac-sha1",
        "x-log-bodyrawsize": "0",
        "Host": host,
        "Accept": "application/json",
    }
    headers["Authorization"] = sign(method, uri_path, query, headers)
    req = urllib.request.Request(url, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def probe():
    found = []
    for r in REGIONS:
        ep = "%s.log.aliyuncs.com" % r
        try:
            code, body = request(ep, "GET", "/", [], timeout=8)
        except Exception as e:
            code, body = -1, str(e)
        if code == 200:
            found.append((r, ep, body[:300]))
            print("[HIT] %-24s %s" % (ep, body[:200]))
            break
        else:
            print("[..] %-24s code=%s %s" % (ep, code, body[:80].replace("\n", " ")))
    return found


if __name__ == "__main__":
    hits = probe()
    print("\n=== RESULT ===")
    print(json.dumps([h[0] for h in hits], ensure_ascii=False))
    if hits:
        region, ep, _ = hits[0]
        code, body = request(ep, "GET", "/logstores")
        print("logstores code=%s" % code)
        print(body[:3000])
