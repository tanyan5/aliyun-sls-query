# -*- coding: utf-8 -*-
"""拉取 inc-backend 近15分钟全部日志，本地解析统计请求分布"""
import sys, json, re, time
from collections import Counter, defaultdict

sys.path.insert(0, ".")
from sls_query import get_logs, LOGSTORE, PROJECT

sys.stdout.reconfigure(encoding='utf-8')

RE_LVL = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} (DEBUG|INFO|WARN|ERROR|TRACE)")
RE_URI = re.compile(r"RUI = \[([^\]]*)\]")
RE_OP = re.compile(r"操作人\s*=\s*(\S+)")
RE_API = re.compile(r"\[inc\]-\[([^\]]*)\]")
RE_COST = re.compile(r"耗时 = \[(\d+)\]")
RE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

NUM_SEG = re.compile(r"^(?:\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{16,})$")


def norm_uri(u):
    """把路径中的数字/UUID 段替换为 {id}，便于归并"""
    parts = u.split("?")[0].split("/")
    out = []
    for p in parts:
        out.append("{id}" if NUM_SEG.match(p) else p)
    return "/".join(out)


def fetch_all(minutes=15):
    now = int(time.time())
    frm, to = now - minutes * 60, now
    all_recs = []
    offset = 0
    while True:
        code, body = get_logs("", frm=frm, to=to, line=100, offset=offset, reverse=False)
        if code != 200:
            print("ERR code=%s %s" % (code, body[:300]))
            break
        try:
            data = json.loads(body)
        except Exception:
            print("parse fail:", body[:300])
            break
        if not data:
            break
        all_recs.extend(data)
        if len(data) < 100:
            break
        offset += 100
        if offset > 2000:
            break
    return frm, to, all_recs


def main():
    minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    frm, to, recs = fetch_all(minutes)
    print("Project: %s | Logstore: %s" % (PROJECT, LOGSTORE))
    print("时间窗口: %s ~ %s  (近 %d 分钟)" % (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(frm)),
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(to)), minutes))
    print("日志总条数: %d" % len(recs))

    lvl = Counter()
    uri_raw = Counter()
    uri_norm = Counter()
    api = Counter()
    cost = defaultdict(list)
    errs = []
    pods = Counter()
    ops = Counter()
    for r in recs:
        c = r.get("content", "")
        m = RE_LVL.match(c)
        if m:
            lvl[m.group(1)] += 1
        pods[r.get("__tag__:_pod_name_", "?")] += 1
        mu = RE_URI.search(c)
        if mu:
            u = mu.group(1)
            uri_raw[u] += 1
            uri_norm[norm_uri(u)] += 1
            mc = RE_COST.search(c)
            if mc:
                cost[norm_uri(u)].append(int(mc.group(1)))
        ma = RE_API.search(c)
        if ma:
            api[ma.group(1)] += 1
        mo = RE_OP.search(c)
        if mo:
            ops[mo.group(1)] += 1
        if m and m.group(1) == "ERROR":
            errs.append(c[:220])
        elif " ERROR " in c:
            errs.append(c[:220])

    print("\n--- 日志级别分布 ---")
    for k, v in lvl.most_common():
        print("  %-6s %d" % (k, v))

    print("\n--- 请求 URI TOP（归一化后，数字/UUID 已折叠为 {id}）---")
    for k, v in uri_norm.most_common(25):
        print("  %-6d %s" % (v, k))

    print("\n--- 请求 URI TOP（原始路径）---")
    for k, v in uri_raw.most_common(25):
        print("  %-6d %s" % (v, k))

    print("\n--- 接口(Controller.method) TOP ---")
    for k, v in api.most_common(25):
        print("  %-6d %s" % (v, k))

    print("\n--- 耗时统计（ms）---")
    stat = sorted(((k, max(v), sum(v) // len(v), len(v)) for k, v in cost.items()),
                  key=lambda x: -x[1])
    print("  %-52s %8s %8s %6s" % ("URI", "max", "avg", "次数"))
    for k, mx, av, n in stat[:15]:
        print("  %-52s %8d %8d %6d" % (k[:52], mx, av, n))

    print("\n--- Pod 分布 ---")
    for k, v in pods.most_common():
        print("  %-6d %s" % (v, k))

    print("\n--- 操作人(工号)分布 (仅成功请求行含操作人) ---")
    for k, v in ops.most_common():
        print("  %-12s %d" % (k, v))

    print("\n--- ERROR 日志 (%d 条, 最多显示 15) ---" % len(errs))
    for e in errs[:15]:
        print("  " + e)

    # 非业务请求日志（框架/连接池/WARN）内容归类
    RE_BODY = re.compile(r"^\S+ \S+ \w+\s+\[[^\]]*\] \[[^\]]*\]\s*(.*)")
    other = Counter()
    for r in recs:
        c = r.get("content", "")
        if RE_URI.search(c):
            continue
        m = RE_BODY.match(c)
        body = m.group(1) if m else c
        key = re.sub(r"\d+", "#", body)[:70]
        other[key] += 1
    print("\n--- 非请求类日志内容 TOP ---")
    for k, v in other.most_common(15):
        print("  %-6d %s" % (v, k))


if __name__ == "__main__":
    main()
