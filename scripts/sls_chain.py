# -*- coding: utf-8 -*-
"""打印某 traceId 的完整链路：只保留 SQL 骨架(Preparing)、关键参数摘要、Total/Updates 与业务日志"""
import sys, json, time, re
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
import sls_trace as t


def summarize(c):
    """把一条日志压缩成一行要点"""
    c = c.strip()
    m = re.search(r'(\w+): ==>\s+Preparing: (.*)$', c)
    if m:
        return 'PREPARE [%s] %s' % (m.group(1), m.group(2).strip())
    m = re.search(r'(\w+): ==> Parameters: (.*)$', c)
    if m:
        p = m.group(2).strip()
        return 'PARAMS  [%s] %s' % (m.group(1), p[:400])
    m = re.search(r'(\w+): <==\s+(Total|Updates): (\d+)', c)
    if m:
        return 'RESULT  [%s] %s=%s' % (m.group(1), m.group(2), m.group(3))
    if 'LogAspect' in c:
        idx = c.find('LogAspect')
        head = c[:idx].strip()
        return 'ASPECT  %s | %s' % (head, c[idx:idx + 160])
    return 'LOG     ' + c[:400]


if __name__ == '__main__':
    tid = sys.argv[1]
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    kw = sys.argv[3] if len(sys.argv) > 3 else None
    now = int(time.time())
    frm = now - hours * 3600
    rs = t.fetch_all(tid, frm, now, max_lines=2000)
    print('trace=%s 记录数=%d 窗口=%s ~ %s' % (
        tid, len(rs),
        time.strftime('%m-%d %H:%M:%S', time.localtime(frm)),
        time.strftime('%m-%d %H:%M:%S', time.localtime(now))))
    for r in rs:
        c = r.get('content', '')
        if kw and kw not in c:
            continue
        print('%s | %s' % (t.tstr(r), summarize(c)))
