# -*- coding: utf-8 -*-
"""拉取指定秒级时间窗内的全部日志（用于观察某次任务的上下文）"""
import sys, json, time, datetime, re
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
import sls_trace as t

# 用法: python sls_window.py "2026-09-30 11:11:00" "2026-09-30 11:11:12" [max lines]
start = sys.argv[1]
end = sys.argv[2]
max_lines = int(sys.argv[3]) if len(sys.argv) > 3 else 200
TZ = 8 * 3600


def to_ts(s):
    dt = datetime.datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
    return int(dt.timestamp())


frm, to = to_ts(start), to_ts(end)
print('窗口 %s ~ %s' % (start, end))
out = []
off = 0
while off < max_lines:
    code, body = t.get_logs('', frm=frm, to=to, line=100, offset=off, reverse=False)
    if code != 200:
        print('HTTP', code, body[:400])
        break
    try:
        d = json.loads(body)
    except Exception:
        print(body[:400])
        break
    if not d:
        break
    out.extend(d)
    if len(d) < 100:
        break
    off += len(d)
print('共', len(out), '条')
for r in out:
    c = r.get('content', '').strip()
    print('%s | %s' % (t.tstr(r), c[:500]))
