# -*- coding: utf-8 -*-
"""通用「save 类接口」参数变更比对工具（状态叠加模型）。

解决两类典型坑（详见 SKILL.md 坑 F/G/H）：
  坑 F  PC/APP 双端 URI 混淆 -> 自动按 RUI 里的 /app/ 分类 endpoint
  坑 G  增量保存不能两次相减 -> 整单快照=整体替换，增量=按业务主键更新对应行，逐次叠加
  坑 H  操作人(工号)只在行尾 -> 自动用正则提取 operator/IP

用法（默认走 UAT；查生产设环境变量 SLS_PROJECT/SLS_LOGSTORE）：
  python sls_savecompare.py <logstore> <keyword> <hours> [max_lines]
      [--list-key merchandiseListSaveList]
      [--item-key merchandiseCode]
      [--owner-key orderCode] [--owner-value BHCG1039HF2258261018-1]
      [--name-key merchandiseName]
      [--qty-keys orderQuantity,adjustQuantity]
      [--del-key delMerchandiseCodeList]
      [--full-threshold 20]
      [--cache <raw.json>]        # 跳过 SLS 直接读落盘的原始记录（调试/复算用）
      [--out-dir .]
      [--include-failed]

输出：savecompare_report.md / savecompare_changes.csv /
      savecompare_final_vs_initial.csv / savecompare_raw.json
"""
import sys, os, json, re, time, argparse
from collections import OrderedDict, Counter

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sls_search import fetch_all, operator_of, endpoint_of, RE_URI, RE_TID, tstr  # noqa


# ---------- 从日志行中提取参数 JSON（大括号平衡，支持嵌套） ----------
def _balanced_from(content, start):
    """从 content[start]（必须是 '{'）开始，按括号平衡截出完整 JSON。"""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(content)):
        ch = content[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return content[start:i + 1]
    return None


def _iter_top_objects(content):
    """yield 所有顶层 {...} 的 (start, end)（平衡且不在字符串内）。"""
    i = 0
    n = len(content)
    while i < n:
        if content[i] == '{':
            seg = _balanced_from(content, i)
            if seg:
                yield i, i + len(seg)
                i += len(seg)
                continue
        i += 1


def extract_param(content, primary="param", list_key="merchandiseListSaveList"):
    """从日志行里截出方法入参 JSON。

    常见写法：
      - `param = {"arg0":{...}}`（inc-backend 的 LogAspect 风格，参数包了一层 arg0）
      - `arg0 = {...}`（直接序列化 args）
    策略：依次尝试锚点 primary -> param -> arg0；仍失败则扫描全文中
    含 list_key 的那个顶层 JSON 对象（最通用兜底）。
    """
    for anchor in dict.fromkeys([primary, "param", "arg0"]):
        m = re.search(re.escape(anchor) + r'\s*=\s*\{', content)
        if m:
            seg = _balanced_from(content, m.end() - 1)
            if seg:
                return seg
    # 兜底：找含 list_key 的顶层对象
    for s, e in _iter_top_objects(content):
        seg = content[s:e]
        if '"%s"' % list_key in seg:
            return seg
    return None


def extract_result_code(content):
    m = re.search(r'result\s*=\s*\{[^{}]*\}', content)
    if not m:
        return "?"
    try:
        return json.loads(m.group(0).split('=', 1)[1].strip()).get("code", "?")
    except Exception:
        return "?"


def qty_str(item, qty_keys):
    return ";".join("%s=%s" % (k, item.get(k)) for k in qty_keys)


# ---------- 解析单条记录 ----------
def parse_record(raw, cfg):
    content = raw.get("content", "")
    pj = extract_param(content, cfg["list_anchor"], cfg["list_key"])
    if not pj:
        return None
    try:
        arg0 = json.loads(pj)
    except Exception:
        return None
    # 拆掉日志里常见的单键包装层，如 arg0 = {"arg0": {...}} -> {...}
    while isinstance(arg0, dict) and len(arg0) == 1 and isinstance(next(iter(arg0.values())), dict):
        arg0 = next(iter(arg0.values()))
    items = arg0.get(cfg["list_key"]) or []
    dels = arg0.get(cfg["del_key"]) or []
    owner_val = raw.get("__owner__")  # 来自 --owner-value 的全局过滤（可选）
    if cfg["owner_value"]:
        items = [it for it in items if str(it.get(cfg["owner_key"], "")) == cfg["owner_value"]]
    if not items and not dels:
        return None
    return {
        "time": raw.get("__time__"),
        "tstr": tstr(raw) if raw.get("__time__") else "?",
        "operator": operator_of(content),
        "endpoint": endpoint_of(content),
        "trace": (RE_TID.search(content).group(1) if RE_TID.search(content) else "?"),
        "uri": (RE_URI.search(content).group(1) if RE_URI.search(content) else "?"),
        "pod": raw.get("__tag__:_pod_name_", "?"),
        "arg0": arg0,
        "items": items,
        "dels": dels,
        "result_code": extract_result_code(content),
        "is_full": len(items) >= cfg["full_threshold"],
    }


# ---------- 状态叠加 ----------
def stack(records, cfg):
    steps = []
    state = OrderedDict()  # key -> item
    prev = {}

    def keyof(it):
        if cfg["owner_value"]:
            return str(it.get(cfg["item_key"], ""))
        return (str(it.get(cfg["owner_key"], "")), str(it.get(cfg["item_key"], "")))

    for idx, rec in enumerate(records, 1):
        items = rec["items"]
        dels = [str(d) for d in rec["dels"]]
        if rec["is_full"]:
            new_state = OrderedDict()
            for it in items:
                new_state[keyof(it)] = dict(it)
        else:
            new_state = OrderedDict((k, dict(v)) for k, v in state.items())
            for it in items:
                new_state[keyof(it)] = dict(it)
        for d in dels:
            new_state.pop(d, None)

        # 计算本次与上一次的差异
        added, removed, changed = [], [], []
        for k, it in new_state.items():
            if k not in prev:
                added.append(k)
            elif qty_str(prev[k], cfg["qty_keys"]) != qty_str(it, cfg["qty_keys"]):
                changed.append(k)
        for k in prev:
            if k not in new_state:
                removed.append(k)

        steps.append({
            "idx": idx, "tstr": rec["tstr"], "operator": rec["operator"],
            "endpoint": rec["endpoint"], "trace": rec["trace"], "pod": rec["pod"],
            "is_full": rec["is_full"], "n_items": len(items), "dels": dels,
            "added": added, "removed": removed, "changed": changed,
            "snapshot": {k: dict(v) for k, v in new_state.items()},
        })
        prev = {k: dict(v) for k, v in new_state.items()}
        state = new_state

    initial = steps[0]["snapshot"] if steps else {}
    final = steps[-1]["snapshot"] if steps else {}
    return steps, initial, final


# ---------- 输出 ----------
def build_outputs(steps, initial, final, cfg, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    final_keys = set(final.keys())
    init_keys = set(initial.keys())
    added_keys = [k for k in final_keys if k not in init_keys]
    removed_keys = [k for k in init_keys if k not in final_keys]
    changed_keys = [k for k in final_keys & init_keys
                    if qty_str(initial[k], cfg["qty_keys"]) != qty_str(final[k], cfg["qty_keys"])]

    # 名称映射
    name_of = {}
    for st in steps:
        for k, it in st["snapshot"].items():
            nm = it.get(cfg["name_key"])
            if nm:
                name_of[k] = nm

    def disp(k):
        return k if isinstance(k, str) else k[1]

    # --- Markdown 报告 ---
    L = []
    L.append("# save 接口参数变更比对报告\n")
    L.append("- 接口关键字：`%s`" % cfg["keyword"])
    L.append("- 物料列表字段：`%s`｜主键：`%s`" % (cfg["list_key"], cfg["item_key"]))
    if cfg["owner_value"]:
        L.append("- 归属过滤：`%s = %s`" % (cfg["owner_key"], cfg["owner_value"]))
    L.append("- 操作次数：**%d**（成功保存）｜端点：%s" % (
        len(steps), dict(Counter(s["endpoint"] for s in steps))))
    ops = Counter(s["operator"] for s in steps)
    L.append("- 操作人(工号)：%s" % (", ".join("%s×%d" % (o, c) for o, c in ops.items()) or "无"))
    L.append("- 物料总数：%d → %d（新增 %d，删除 %d，净变更 %d 项）\n" % (
        len(initial), len(final), len(added_keys), len(removed_keys), len(changed_keys)))

    L.append("## 完整操作流水（按时间升序）\n")
    for st in steps:
        kind = "整单快照" if st["is_full"] else "增量"
        L.append("### 第 %d 次 — %s ［%s / %s，%s］" % (
            st["idx"], st["tstr"], st["endpoint"], st["operator"], kind))
        L.append("- traceId: `%s`｜pod: `%s`｜本次携带物料行数: %d" % (
            st["trace"], st["pod"], st["n_items"]))
        if st["idx"] == 1:
            L.append("- 录入基线：%d 个物料（初始快照，不计为改动）" % len(st["snapshot"]))
            continue
        if st["dels"]:
            L.append("- 删除: " + "; ".join("`%s`(%s)" % (d, name_of.get(d, "")) for d in st["dels"]))
        if st["added"]:
            L.append("- 新增: " + "; ".join("`%s` %s（%s）" % (
                k, disp(k), name_of.get(k, "")) for k in st["added"]))
        if st["changed"]:
            prev_snap = steps[st["idx"] - 2]["snapshot"] if st["idx"] > 1 else {}
            for k in st["changed"]:
                b = qty_str(prev_snap.get(k, {}), cfg["qty_keys"])
                a = qty_str(st["snapshot"].get(k, {}), cfg["qty_keys"])
                L.append("- 变更: `%s`(%s) %s → %s" % (k, name_of.get(k, ""), b, a))
        if not (st["added"] or st["removed"] or st["changed"]):
            L.append("- (相对上一次无差异)")

    L.append("\n## 净变更汇总（最终 vs 初始）\n")
    L.append("- 新增 %d 项：%s" % (len(added_keys),
        "；".join("`%s`(%s)" % (k, name_of.get(k, "")) for k in added_keys) or "无"))
    L.append("- 删除 %d 项：%s" % (len(removed_keys),
        "；".join("`%s`(%s)" % (k, name_of.get(k, "")) for k in removed_keys) or "无"))
    L.append("\n### 数量净变更明细（%d 项）\n" % len(changed_keys))
    rows = []
    for k in changed_keys:
        b = qty_str(initial[k], cfg["qty_keys"])
        a = qty_str(final[k], cfg["qty_keys"])
        rows.append((k, name_of.get(k, ""), b, a))
    # 按第一个 qty 字段的 delta 排序（涨在前）
    def delta_num(s):
        try:
            return float(str(s).split("=")[1].split(";")[0])
        except Exception:
            return 0
    rows.sort(key=lambda r: -delta_num(r[3]) + delta_num(r[2]))
    for k, nm, b, a in rows:
        L.append("- `%s`(%s)：%s → %s" % (k, nm, b, a))

    md_path = os.path.join(out_dir, "savecompare_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    # --- 逐次变更长表 CSV ---
    csv_rows = [["step", "time", "endpoint", "operator", "change_type",
                 cfg["item_key"], cfg["name_key"]] + ["before_" + k for k in cfg["qty_keys"]] +
                ["after_" + k for k in cfg["qty_keys"]]]
    for st in steps:
        prev_snap = steps[st["idx"] - 2]["snapshot"] if st["idx"] > 1 else {}
        cur = st["snapshot"]
        if st["idx"] == 1:
            continue  # 基线快照不计入改动行
        for k in st["added"]:
            it = cur[k]
            csv_rows.append([st["idx"], st["tstr"], st["endpoint"], st["operator"], "add",
                             disp(k), name_of.get(k, "")] +
                            [""] * len(cfg["qty_keys"]) +
                            [it.get(kk) for kk in cfg["qty_keys"]])
        for k in st["removed"]:
            it = prev_snap.get(k, {})
            csv_rows.append([st["idx"], st["tstr"], st["endpoint"], st["operator"], "remove",
                             disp(k), name_of.get(k, "")] +
                            [it.get(kk) for kk in cfg["qty_keys"]] + [""] * len(cfg["qty_keys"]))
        for k in st["changed"]:
            b = prev_snap.get(k, {})
            a = cur[k]
            csv_rows.append([st["idx"], st["tstr"], st["endpoint"], st["operator"], "change",
                             disp(k), name_of.get(k, "")] +
                            [b.get(kk) for kk in cfg["qty_keys"]] +
                            [a.get(kk) for kk in cfg["qty_keys"]])
    csv_path = os.path.join(out_dir, "savecompare_changes.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        import csv as _csv
        _csv.writer(f).writerows(csv_rows)

    # --- 最终 vs 初始 全量 CSV ---
    fv_rows = [["key", cfg["name_key"]] +
               ["init_" + k for k in cfg["qty_keys"]] +
               ["final_" + k for k in cfg["qty_keys"]] +
               ["delta_" + k for k in cfg["qty_keys"]] + ["status"]]
    all_keys = list(initial.keys()) + [k for k in final if k not in initial]
    for k in all_keys:
        b = initial.get(k, {})
        a = final.get(k, {})
        status = "added" if k not in initial else ("removed" if k not in final else "changed" if qty_str(b, cfg["qty_keys"]) != qty_str(a, cfg["qty_keys"]) else "unchanged")
        fv_rows.append([disp(k), name_of.get(k, "")] +
                       [b.get(kk) for kk in cfg["qty_keys"]] +
                       [a.get(kk) for kk in cfg["qty_keys"]] +
                       [( (float(a.get(kk) or 0)) - (float(b.get(kk) or 0)) ) for kk in cfg["qty_keys"]] +
                       [status])
    fv_path = os.path.join(out_dir, "savecompare_final_vs_initial.csv")
    with open(fv_path, "w", encoding="utf-8-sig", newline="") as f:
        import csv as _csv
        _csv.writer(f).writerows(fv_rows)

    return md_path, csv_path, fv_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logstore", nargs="?", default=os.environ.get("SLS_LOGSTORE", "inc-backend"))
    ap.add_argument("keyword", nargs="?", default="saveOrderQuantity")
    ap.add_argument("hours", nargs="?", type=int, default=24)
    ap.add_argument("max_lines", nargs="?", type=int, default=1000)
    ap.add_argument("--list-key", default="merchandiseListSaveList")
    ap.add_argument("--list-anchor", default="param")
    ap.add_argument("--item-key", default="merchandiseCode")
    ap.add_argument("--owner-key", default="orderCode")
    ap.add_argument("--owner-value", default="")
    ap.add_argument("--name-key", default="merchandiseName")
    ap.add_argument("--qty-keys", default="orderQuantity,adjustQuantity")
    ap.add_argument("--del-key", default="delMerchandiseCodeList")
    ap.add_argument("--full-threshold", type=int, default=20)
    ap.add_argument("--cache", default="")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--include-failed", action="store_true")
    args = ap.parse_args()

    cfg = {
        "keyword": args.keyword,
        "list_key": args.list_key,
        "list_anchor": args.list_anchor or "param",
        "item_key": args.item_key,
        "owner_key": args.owner_key,
        "owner_value": args.owner_value,
        "name_key": args.name_key,
        "qty_keys": [k for k in args.qty_keys.split(",") if k],
        "del_key": args.del_key,
        "full_threshold": args.full_threshold,
    }

    if args.cache:
        raw = json.load(open(args.cache, encoding="utf-8"))
        recs = []
        for r in raw:
            recs.append({
                "content": r.get("content", ""),
                "__time__": r.get("__time__"),
                "__tag__:_pod_name_": r.get("__tag__:_pod_name_", "?"),
            })
        print("从缓存载入: %d 条原始记录" % len(recs))
    else:
        now = int(time.time())
        frm, to = now - args.hours * 3600, now
        print("拉取 %s 中匹配 '%s' 的日志 (%d 小时)..." % (args.logstore, args.keyword, args.hours))
        raw_sls = fetch_all(args.logstore, args.keyword, frm, to, max_lines=args.max_lines)
        recs = []
        for r in raw_sls:
            recs.append({
                "content": r.get("content", ""),
                "__time__": r.get("__time__"),
                "__tag__:_pod_name_": r.get("__tag__:_pod_name_", "?"),
            })
        print("命中原始记录: %d 条" % len(recs))

    parsed = []
    for r in recs:
        p = parse_record(r, cfg)
        if not p:
            continue
        if not args.include_failed and p["result_code"] not in ("?", "SUCCESS"):
            continue
        parsed.append(p)

    # 按时间升序
    parsed.sort(key=lambda x: x["time"] or 0)
    print("可解析的保存操作(成功): %d 条" % len(parsed))

    # 落盘原始（便于复算）
    os.makedirs(args.out_dir, exist_ok=True)
    raw_path = os.path.join(args.out_dir, "savecompare_raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump([p for p in parsed], f, ensure_ascii=False, indent=1, default=str)

    if not parsed:
        print("没有可解析的保存记录，退出。")
        return

    steps, initial, final = stack(parsed, cfg)
    md, csv1, csv2 = build_outputs(steps, initial, final, cfg, args.out_dir)
    print("报告已生成:")
    print("  ", md)
    print("  ", csv1)
    print("  ", csv2)
    print("  ", raw_path)


if __name__ == "__main__":
    main()
