# -*- coding: utf-8 -*-
"""逐条 trace 检索指定物料编码出现的位置"""
import sys, re, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
import sls_trace as t

CODE = sys.argv[1] if len(sys.argv) > 1 else '1200002156'
HOURS = int(sys.argv[2]) if len(sys.argv) > 2 else 24
TRACES = sys.argv[3].split(',') if len(sys.argv) > 3 else [
    'd2e2f16306adaf84', 'f328bdee2fe649b5', '1508e7ae17763bcf', '29296b1aa0099ba3']

now = int(time.time())
frm = now - HOURS * 3600

for tid in TRACES:
    rs = t.fetch_all(tid, frm, now, max_lines=2000)
    hit = [r for r in rs if CODE in r.get('content', '')]
    print('\n===== trace %s  总日志 %d 条，命中 %s 的 %d 条 =====' % (tid, len(rs), CODE, len(hit)))
    # 命中行之后的 RESULT 行（不含物料码）也要带上
    expanded = []
    for i, r in enumerate(rs):
        if CODE in r.get('content', ''):
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
