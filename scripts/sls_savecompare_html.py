# -*- coding: utf-8 -*-
"""根据 sls_savecompare.py 的产物，生成报货单改动汇总 HTML（自包含、可直接分享）。

样式 1:1 沿用第一版（首份报货单改动汇报 HTML 的样式）；
数据从 savecompare_raw.json 重放状态叠加重建时间线（修复 changes.csv 端点/分步 bug），
净变更/新增/删除取自已验证的 savecompare_final_vs_initial.csv。

依赖：sls_savecompare.py 已产出（默认在同目录/--indir 下）：
  - savecompare_raw.json
  - savecompare_final_vs_initial.csv

用法：
  # 先跑比对
  python sls_savecompare.py <logstore> "<keyword> <order>" 40 \
      --owner-key orderCode --owner-value <ORDER> --out-dir out
  # 再生成 HTML（样式与之前一致）
  python sls_savecompare_html.py --order <ORDER> --store <STORECODE> \
      --src "<module>-backend（阿里云 SLS）" \
      --window "2026-10-19 00:00:00 ~ 2026-10-19 12:35" --indir out
"""
import argparse
import csv
import html
import json

# ---------- 参数 ----------
ap = argparse.ArgumentParser()
ap.add_argument("--order", required=True, help="报货单号，例如 <订单号>")
ap.add_argument("--store", required=True, help="门店 storeCode（带业务前缀，如 1_<门店号>）")
ap.add_argument("--src", default="（阿里云 SLS）",
                help="数据来源描述，例如 <module>-backend（阿里云 SLS）")
ap.add_argument("--window", default="", help="时间窗口描述，例如 2026-10-19 00:00:00 ~ 2026-10-19 12:35")
ap.add_argument("--indir", default=".", help="sls_savecompare.py 产物所在目录（含 *_raw.json 与 *_final_vs_initial.csv）")
ap.add_argument("--out", default="save_order_report.html", help="输出 HTML 文件名")
ap.add_argument("--qty-key", default="orderQuantity", help="final_vs_initial.csv 中用于统计的订货量列，默认 orderQuantity")
ap.add_argument("--name-key", default="merchandiseName", help="物料名称列名")
args = ap.parse_args()

ORDER = args.order
STORE = args.store
SRC = args.src
WIN = args.window
QTY = args.qty_key
NAMEKEY = args.name_key

import os
RAW = os.path.join(args.indir, "savecompare_raw.json")
FULL = os.path.join(args.indir, "savecompare_final_vs_initial.csv")
INIT_COL = "init_" + QTY
FINAL_COL = "final_" + QTY
DELTA_COL = "delta_" + QTY


def fnum(x):
    try:
        if x is None:
            return None
        x = str(x).strip()
        if x in ("", "(无)", "None", "nan"):
            return None
        return float(x)
    except Exception:
        return None


# ---- 从 raw json 重放状态叠加，重建每一步的差异 ----
with open(RAW, encoding="utf-8") as f:
    raw = json.load(f)
recs = sorted(raw, key=lambda r: r["time"])


def state_from_items(items):
    st = {}
    for it in items:
        code = it.get("merchandiseCode")
        if code is None:
            continue
        st[code] = {"qty": it.get(QTY), "name": it.get(NAMEKEY)}
    return st


steps = {}
prev = None
for i, r in enumerate(recs, 1):
    items = r.get("items") or []
    dels = r.get("dels") or []
    is_full = r.get("is_full")
    if is_full:
        new_st = state_from_items(items)
    else:
        new_st = dict(prev) if prev is not None else {}
        for it in items:
            code = it.get("merchandiseCode")
            if code is None:
                continue
            new_st[code] = {"qty": it.get(QTY), "name": it.get(NAMEKEY)}
        for code in dels:
            new_st.pop(code, None)
    rows = []
    if prev is not None:
        prev_codes = set(prev)
        new_codes = set(new_st)
        for code in new_codes:
            n = new_st[code]
            p = prev.get(code)
            if p is None:
                rows.append({"变更类型": "新增", "物料编码": code, "物料名称": n["name"],
                             "变更前订货量": "(无)", "变更后订货量": n["qty"], "订货量Δ": ""})
            else:
                d = (fnum(n["qty"]) or 0) - (fnum(p["qty"]) or 0)
                if d != 0:
                    rows.append({"变更类型": "变更", "物料编码": code, "物料名称": n["name"],
                                 "变更前订货量": p["qty"], "变更后订货量": n["qty"], "订货量Δ": d})
        for code in prev_codes - new_codes:
            p = prev[code]
            rows.append({"变更类型": "删除", "物料编码": code, "物料名称": p["name"],
                         "变更前订货量": p["qty"], "变更后订货量": "(无)", "订货量Δ": ""})
    # 按物料编码确定性排序，避免 set 迭代顺序导致每次输出不一致
    rows.sort(key=lambda r: str(r.get("物料编码", "")))
    steps[i] = {
        "operator": r.get("operator"), "src": r.get("endpoint"), "time": r.get("tstr"),
        "type": ("整单快照" if is_full else "增量"), "trace": r.get("trace"),
        "is_full": is_full, "rows": rows,
    }
    prev = new_st
final_state = prev

# ---- 从已验证的 FULL 表取 净变更/新增/删除 ----
net, added, removed = [], [], []
with open(FULL, encoding="utf-8-sig") as f:
    full_rows = list(csv.DictReader(f))
for r in full_rows:
    code = r["key"]
    name = r[NAMEKEY]
    st = r["status"]
    o0 = r.get(INIT_COL)
    o1 = r.get(FINAL_COL)
    d = r.get(DELTA_COL)
    if st == "added":
        added.append((code, name, o1))
    elif st == "removed":
        removed.append((code, name, o0))
    elif st == "changed":
        dd = fnum(d)
        if dd not in (0, None):
            net.append((code, name, o0, o1, dd))
net.sort(key=lambda x: -abs(x[4]))
added.sort()
removed.sort()

INIT_N = len([r for r in full_rows if r["status"] != "added"])
FINAL_N = len(full_rows)
N_OPS = len(steps)
N_PC = sum(1 for s in steps.values() if s["src"] == "PC")
N_APP = sum(1 for s in steps.values() if s["src"] == "APP")
OPS = sorted({s["operator"] for s in steps.values()})
by_op = {}
for seq, s in steps.items():
    by_op.setdefault(s["operator"], []).append((seq, s))


def esc(x):
    return html.escape(str(x if x is not None else ""))


def change_row(r):
    ctype = r["变更类型"]
    code = r["物料编码"]
    name = r["物料名称"]
    b = r["变更前订货量"]
    a = r["变更后订货量"]
    d = r["订货量Δ"]
    cls = {"新增": "add", "删除": "del", "变更": "chg"}[ctype]
    if ctype == "新增":
        arrow = "<b class='add'>＋新增</b> → <b>%s</b>" % esc(a)
    elif ctype == "删除":
        arrow = "<b class='del'>－删除</b> 原 <b>%s</b>" % esc(b)
    else:
        dcls = "up" if (fnum(d) or 0) > 0 else ("down" if (fnum(d) or 0) < 0 else "")
        arrow = "%s → <b>%s</b> <span class='delta %s'>(%s%s)</span>" % (
            esc(b), esc(a), dcls, "+" if (fnum(d) or 0) > 0 else "", esc(d))
    return "<div class='crow %s'><span class='ccode'>%s</span><span class='cname'>%s</span><span class='carrow'>%s</span></div>" % (
        cls, esc(code), esc(name), arrow)


# ---- 构建 HTML（CSS 与第一次完全一致）----
L = []
L.append("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>报货单 %s 改动流水汇报</title>
<style>
:root{--bg:#f5f7fa;--card:#fff;--ink:#1f2937;--mut:#6b7280;--line:#e5e7eb;
--red:#d4380d;--green:#237804;--blue:#0958d9;--amber:#ad6800;}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink);line-height:1.55;padding:28px 18px 60px}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:18px}
.cards{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0 22px}
.card{flex:1;min-width:150px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .n{font-size:26px;font-weight:700}
.card .l{font-size:12px;color:var(--mut);margin-top:2px}
h2{font-size:17px;margin:30px 0 12px;padding-left:10px;border-left:4px solid var(--blue)}
.opgrid{display:flex;gap:14px;flex-wrap:wrap}
.opcard{flex:1;min-width:300px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.opcard h3{margin:0 0 6px;font-size:15px}
.opcard .meta{font-size:12px;color:var(--mut);margin-bottom:8px}
.opline{font-size:13px;padding:3px 0;border-bottom:1px dashed var(--line)}
.opline b{color:var(--blue)}
.timeline{position:relative;margin:10px 0 0;padding-left:0}
.step{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:14px}
.step .hd{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.step .num{background:var(--blue);color:#fff;width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px}
.step .t{font-weight:700}
.tag{font-size:11px;padding:2px 8px;border-radius:20px;border:1px solid var(--line);color:var(--mut)}
.tag.pc{background:#e6f4ff;color:#0958d9;border-color:#91caff}
.tag.app{background:#f9f0ff;color:#531dab;border-color:#d3adf7}
.tag.op{background:#f6ffed;color:#237804;border-color:#b7eb8f}
.crow{display:flex;gap:10px;font-size:13px;padding:2px 0;align-items:baseline}
.crow.add .ccode{color:var(--blue)} .crow.del .ccode{color:var(--green)}
.ccode{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--mut);min-width:96px}
.cname{flex:1}
.carrow{min-width:210px;text-align:right}
.add{color:var(--blue)} .del{color:var(--green)} .up{color:var(--red)} .down{color:var(--green)}
.delta{font-size:12px}
table{width:100%;border-collapse:collapse;background:var(--card);font-size:13px;margin-top:6px}
th,td{border:1px solid var(--line);padding:6px 10px;text-align:left}
th{background:#fafafa;position:sticky;top:0}
td.r,th.r{text-align:right;font-family:ui-monospace,Menlo,monospace}
.up{color:var(--red)} .down{color:var(--green)} .addc{color:var(--blue)}
.note{background:#fffbe6;border:1px solid #ffe58f;border-radius:10px;padding:12px 14px;font-size:13px;color:#614700;margin:16px 0}
.legend{font-size:12px;color:var(--mut);margin:6px 0 0}
.legend span{display:inline-block;margin-right:14px}
</style></head><body><div class="wrap">""")

L.append("<h1>报货单 %s · 完整改动流水汇报</h1>" % esc(ORDER))
sub = "门店 storeCode = <b>%s</b> ｜ 数据来源：%s" % (esc(STORE), esc(SRC))
if WIN:
    sub += " ｜ 时间窗口 %s" % esc(WIN)
L.append("<div class='sub'>%s</div>" % sub)

# 概览卡片
L.append("<div class='cards'>")
for n, l in [(N_OPS, "成功保存次数"),
             ("%d + %d" % (N_PC, N_APP), "PC + APP 端"),
             ("、".join(OPS), "操作人(工号)"),
             ("%d→%d" % (INIT_N, FINAL_N), "物料项 初始→最终"),
             (len(added), "新增物料"),
             (len(net), "订货量净变更项")]:
    L.append("<div class='card'><div class='n'>%s</div><div class='l'>%s</div></div>" % (esc(n), esc(l)))
L.append("</div>")

L.append("<div class='legend'>配色：<span class='addc'>蓝＝新增</span><span class='up'>红＝订货量↑</span><span class='down'>绿＝订货量↓/删除</span></div>")

# 归属说明（按本单真实数据动态生成）
L.append("<div class='note'>⚠️ <b>PC / APP 双端已按 URI 精确分离</b>：本单共 %d 次保存（PC %d 次 / APP %d 次），APP 端记录由移动端发起，已正确计入、未误并入 PC。其中 APP 端 %d 次分别由操作人 %s 发起。</div>" % (
    N_OPS, N_PC, N_APP, N_APP, "、".join(sorted({steps[s]["operator"] for s in steps if steps[s]["src"] == "APP"}))))

# 操作人视角
L.append("<h2>一、操作人视角</h2>")
L.append("<div class='opgrid'>")
src_label = {"PC": "PC 端", "APP": "APP 端"}
for op in sorted(by_op):
    items = by_op[op]
    srcs = sorted({steps[s]["src"] for s, _ in items})
    times = [steps[s]["time"] for s, _ in items]
    L.append("<div class='opcard'><h3>操作人 <b>%s</b></h3>" % esc(op))
    L.append("<div class='meta'>端：%s ｜ 共 %d 次 ｜ %s ~ %s</div>" % (
        " / ".join(src_label.get(x, x) for x in srcs), len(items), esc(times[0]), esc(times[-1])))
    for seq, s in items:
        nchg = len([r for r in s["rows"] if r["变更类型"] == "变更"])
        nadd = len([r for r in s["rows"] if r["变更类型"] == "新增"])
        ndel = len([r for r in s["rows"] if r["变更类型"] == "删除"])
        det = []
        if nadd:
            det.append("新增%d" % nadd)
        if ndel:
            det.append("删除%d" % ndel)
        if nchg:
            det.append("变更%d" % nchg)
        if not det:
            det.append("无差异(整单重存)")
        L.append("<div class='opline'>[%d] <b>%s</b> · %s · %s：%s</div>" % (
            seq, esc(s["time"]), src_label.get(s["src"], s["src"]), esc(s["type"]), "、".join(det)))
    L.append("</div>")
L.append("</div>")

# 完整流水
L.append("<h2>二、完整改动流水（按时间升序，共 %d 步）</h2>" % N_OPS)
for seq in sorted(steps):
    s = steps[seq]
    L.append("<div class='step'>")
    L.append("<div class='hd'><span class='num'>%d</span><span class='t'>%s</span>" % (seq, esc(s["time"])))
    L.append("<span class='tag %s'>%s</span>" % (s["src"].lower(), src_label.get(s["src"], s["src"])))
    L.append("<span class='tag op'>操作人 %s</span>" % esc(s["operator"]))
    L.append("<span class='tag'>%s</span>" % esc(s["type"]))
    L.append("<span class='tag'>trace %s</span></div>" % esc((s["trace"] or "")[:12]))
    if seq == 1:
        L.append("<div class='crow'><span class='ccode'>&nbsp;</span><span class='cname'><b class='add'>录入基线：%d 项物料</b>（首次整单快照，作为后续比较基准）</span></div>" % INIT_N)
    else:
        chg = [r for r in s["rows"] if r["变更类型"] == "变更"]
        add = [r for r in s["rows"] if r["变更类型"] == "新增"]
        dele = [r for r in s["rows"] if r["变更类型"] == "删除"]
        if not (chg or add or dele):
            L.append("<div class='crow'><span class='ccode'>&nbsp;</span><span class='cname'>（整单重存，数值较上一次无差异）</span></div>")
        for r in add + dele + chg:
            L.append(change_row(r))
    L.append("</div>")

# 变动点速览
L.append("<h2>三、变动点速览（一眼看清）</h2>")
L.append("<h3 style='font-size:14px;margin:14px 0 6px'>① 新增物料（%d 项）</h3>" % len(added))
if added:
    for code, name, qty in added:
        L.append("<div class='crow'><span class='ccode'>%s</span><span class='cname'>%s</span><span class='carrow'><b class='add'>＋新增 → %s</b></span></div>" % (esc(code), esc(name), esc(qty)))
else:
    L.append("<div class='crow'><span class='cname'>无</span></div>")

L.append("<h3 style='font-size:14px;margin:14px 0 6px'>② 被删除物料（%d 项）</h3>" % len(removed))
if removed:
    for code, name, qty in removed:
        L.append("<div class='crow'><span class='ccode'>%s</span><span class='cname'>%s</span><span class='carrow'><b class='del'>－删除（原 %s）</b></span></div>" % (esc(code), esc(name), esc(qty)))
else:
    L.append("<div class='crow'><span class='cname'>无</span></div>")

downs = [x for x in net if x[4] < 0]
ups = [x for x in net if x[4] > 0]
L.append("<h3 style='font-size:14px;margin:14px 0 6px'>③ 「减量」项（共 %d 项，其余均为增量）</h3>" % len(downs))
if downs:
    for code, name, o0, o1, d in downs:
        L.append("<div class='crow'><span class='ccode'>%s</span><span class='cname'>%s</span><span class='carrow'>%s → <b>%s</b> <span class='delta down'>(%s)</span></span></div>" % (esc(code), esc(name), esc(o0), esc(o1), esc(d)))
else:
    L.append("<div class='crow'><span class='cname'>无</span></div>")

L.append("<h3 style='font-size:14px;margin:14px 0 6px'>④ 增量 Top 8（按变化幅度）</h3>")
L.append("<table><tr><th>物料编码</th><th>名称</th><th class='r'>初始</th><th class='r'>最终</th><th class='r'>Δ</th></tr>")
for code, name, o0, o1, d in ups[:8]:
    L.append("<tr><td class='ccode'>%s</td><td>%s</td><td class='r'>%s</td><td class='r'>%s</td><td class='r up'>%+g</td></tr>" % (esc(code), esc(name), esc(o0), esc(o1), d))
L.append("</table>")

# 完整净变更全表
L.append("<h2>四、订货量净变更全表（共 %d 项，初始→最终）</h2>" % len(net))
L.append("<table><tr><th>物料编码</th><th>名称</th><th class='r'>初始</th><th class='r'>最终</th><th class='r'>Δ</th></tr>")
for code, name, o0, o1, d in net:
    dc = "up" if d > 0 else "down"
    L.append("<tr><td class='ccode'>%s</td><td>%s</td><td class='r'>%s</td><td class='r'>%s</td><td class='r %s'>%+g</td></tr>" % (esc(code), esc(name), esc(o0), esc(o1), dc, d))
L.append("</table>")

L.append("<div class='note' style='margin-top:24px'>说明：saveOrderQuantity 为增量保存接口——整单快照（is_full）按整体替换、少量行按更新对应行；PC 与 APP 同后端，故在共享状态上按时间叠加重建真实演进。完整逐行数据见 <code>savecompare_changes.csv</code> 与 <code>savecompare_final_vs_initial.csv</code>（%d 项）。</div>" % FINAL_N)

L.append("</div></body></html>")

with open(args.out, "w", encoding="utf-8") as f:
    f.write("\n".join(L))
print("已生成 %s" % args.out)
print("操作步=%d, PC=%d, APP=%d, 初始=%d→最终=%d, 新增=%d, 删除=%d, 净变更=%d, 增量=%d, 减量=%d" % (
    N_OPS, N_PC, N_APP, INIT_N, FINAL_N, len(added), len(removed), len(net), len(ups), len(downs)))
