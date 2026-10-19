# -*- coding: utf-8 -*-
"""逐条 trace 检索指定物料编码出现的位置

用法:
  python sls_merch.py <物料编码> [hours] <traceId[,traceId,...]>

示例:
  python sls_merch.py <物料编码> 24 <traceId>[,<traceId>...]
"""
import sys
import os
import re
import time
import argparse

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sls_trace as t  # noqa: E402  （依赖本文件同目录的 sls_trace.py）


def dump_trace(tid, code, frm, to):
    """打印单条 trace 内命中物料编码的日志（含紧随其后的 RESULT 行）"""
    rs = t.fetch_all(tid, frm, to, max_lines=2000)
    hit = [r for r in rs if code in r.get('content', '')]
    print('\n===== trace %s  总日志 %d 条，命中 %s 的 %d 条 ====='
          % (tid, len(rs), code, len(hit)))

    # 命中行之后的 RESULT 行（不含物料码）也要带上
    expanded = []
    for i, r in enumerate(rs):
        if code in r.get('content', ''):
            expanded.append(r)
            for nxt in rs[i + 1:i + 3]:
                if re.search(r'<==\s+(Total|Updates)', nxt.get('content', '')):
                    expanded.append(nxt)
                    break

    for r in expanded:
        c = r.get('content', '').strip()
        m = re.search(r'(\w+): ==>\s+(Preparing|Parameters): (.*)$', c)
        if m:
            print('  %s [%s] %s %s' % (t.tstr(r), m.group(1), m.group(2), m.group(3)[:260]))
            continue
        m = re.search(r'(\w+): <==\s+(Total|Updates): (\d+)', c)
        if m:
            print('  %s [%s] %s=%s' % (t.tstr(r), m.group(1), m.group(2), m.group(3)))
            continue
        print('  %s %s' % (t.tstr(r), c[:260]))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='逐条 trace 检索指定物料编码出现的位置')
    ap.add_argument('code', help='物料编码（merchandiseCode）')
    ap.add_argument('hours', nargs='?', type=int, default=24,
                    help='回溯小时数（默认 24）')
    ap.add_argument('traces', nargs='?',
                    help='traceId 列表，逗号分隔，例如 "abc123,def456"')
    args = ap.parse_args(argv)

    if not args.traces:
        ap.error('缺少 traceId 列表。traceId 会过期，必须显式指定；'
                 '可先用 sls_trace.py 或 sls_search.py 拿到 traceId')
    traces = [x.strip() for x in args.traces.split(',') if x.strip()]
    if not traces:
        ap.error('traceId 列表为空')

    now = int(time.time())
    frm = now - args.hours * 3600
    for tid in traces:
        dump_trace(tid, args.code, frm, now)


if __name__ == '__main__':
    main()
