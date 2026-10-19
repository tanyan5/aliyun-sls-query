# -*- coding: utf-8 -*-
"""拉取指定秒级时间窗内的全部日志（用于观察某次任务的上下文）

用法:
  python sls_window.py "2026-09-30 11:11:00" "2026-09-30 11:11:12" [max_lines]

时间按东八区（日志展示时区）解释，与本机时区无关。
"""
import sys
import os
import json
import datetime
import argparse

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sls_trace as t  # noqa: E402  （依赖本文件同目录的 sls_trace.py）

TZ_OFFSET = 8 * 3600  # 东八区偏移（秒）


def to_ts(s):
    """把 'YYYY-MM-DD HH:MM:SS'（东八区）转成 epoch 秒"""
    dt = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    return int(dt.replace(tzinfo=datetime.timezone.utc).timestamp()) - TZ_OFFSET


def fetch_window(frm, to, max_lines):
    """按 100 条/页拉取 [frm, to] 内的全部日志，最多 max_lines 条"""
    out = []
    off = 0
    while off < max_lines:
        line = min(100, max_lines - off)
        code, body = t.get_logs('', frm=frm, to=to, line=line, offset=off, reverse=False)
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
        if len(d) < line:
            break
        off += len(d)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='拉取指定秒级时间窗内的全部日志（东八区）')
    ap.add_argument('start', help='开始时间，格式 "YYYY-MM-DD HH:MM:SS"')
    ap.add_argument('end', help='结束时间，格式 "YYYY-MM-DD HH:MM:SS"')
    ap.add_argument('max_lines', nargs='?', type=int, default=200,
                    help='最多拉取条数（默认 200）')
    args = ap.parse_args(argv)

    if args.max_lines <= 0:
        ap.error('max_lines 必须为正整数')

    try:
        frm, to = to_ts(args.start), to_ts(args.end)
    except ValueError:
        ap.error('时间格式错误，应为 "YYYY-MM-DD HH:MM:SS"，例如 "2026-09-30 11:11:00"')
    if frm > to:
        ap.error('开始时间晚于结束时间')

    print('窗口 %s ~ %s' % (args.start, args.end))
    out = fetch_window(frm, to, args.max_lines)
    print('共', len(out), '条')
    for r in out:
        c = r.get('content', '').strip()
        print('%s | %s' % (t.tstr(r), c[:500]))


if __name__ == '__main__':
    main()
