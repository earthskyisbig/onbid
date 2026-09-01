#!/usr/bin/env python3
"""
_workspace/ 산출물을 한 페이지 대시보드 HTML 로 묶는다 (오프라인·단일 파일, 데이터 내장).

    python3 scripts/build_dashboard.py                       # _workspace → _workspace/dashboard.html
    python3 scripts/build_dashboard.py --workspace path --output out.html --title "제목"

읽는 파일 (있는 것만):
    01_search_results.json, verification_report_phase1.json, verification_report_phase3.json,
    02_doc_analysis_{id}.json, 02_location_analysis_{id}.json, 03_bid_strategy_{id}.json,
    market_{id}.json, naver_listings_{id}.json, final_report_*.md
템플릿: scripts/templates/dashboard.html (문자열 __DASHBOARD_DATA__ 자리에 JSON 삽입)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORKSPACE  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / 'templates' / 'dashboard.html'
ID_RE = re.compile(r'_(\d{4}-\d+-\d+)\.json$')


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as e:
        return {'_error': f'{path.name}: {e}'}


def _by_id(ws: Path, pattern: str) -> dict:
    out = {}
    for f in sorted(glob.glob(str(ws / pattern))):
        m = ID_RE.search(os.path.basename(f))
        if m:
            out[m.group(1)] = _load(Path(f))
    return out


def collect(ws: Path) -> dict:
    data = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'workspace': str(ws),
        'search': _load(ws / '01_search_results.json') if (ws / '01_search_results.json').exists() else None,
        'verification': {
            'phase1': _load(ws / 'verification_report_phase1.json') if (ws / 'verification_report_phase1.json').exists() else None,
            'phase3': _load(ws / 'verification_report_phase3.json') if (ws / 'verification_report_phase3.json').exists() else None,
        },
        'docs': _by_id(ws, '02_doc_analysis_*.json'),
        'locations': _by_id(ws, '02_location_analysis_*.json'),
        'strategies': _by_id(ws, '03_bid_strategy_*.json'),
        'markets': _by_id(ws, 'market_*.json'),
        'naver': _by_id(ws, 'naver_listings_*.json'),
        'reports': [],
        'files': sorted(os.path.basename(f) for f in glob.glob(str(ws / '*')) if os.path.isfile(f)),
    }
    for f in sorted(glob.glob(str(ws / 'final_report_*.md')), reverse=True):
        data['reports'].append({'name': os.path.basename(f), 'text': Path(f).read_text(encoding='utf-8')})
    return data


def build(ws: Path, out: Path, title: str | None = None) -> Path:
    data = collect(ws)
    if title:
        data['title'] = title
    html = TEMPLATE.read_text(encoding='utf-8')
    payload = json.dumps(data, ensure_ascii=False).replace('</script', '<\\/script')
    html = html.replace('__DASHBOARD_DATA__', payload)
    if title:
        html = html.replace('<title>온비드 공매 대시보드</title>', f'<title>{title}</title>')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding='utf-8')
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description='공매 분석 대시보드 HTML 생성')
    p.add_argument('--workspace', default=str(WORKSPACE))
    p.add_argument('--output', help='기본 {workspace}/dashboard.html')
    p.add_argument('--title')
    args = p.parse_args(argv)
    ws = Path(args.workspace)
    if not ws.exists():
        p.error(f'워크스페이스 없음: {ws}')
    out = Path(args.output or ws / 'dashboard.html')
    build(ws, out, args.title)
    size = out.stat().st_size
    print(f"저장: {out} ({size / 1024:.0f} KB)")
    if size > 15 * 1024 * 1024:
        print("[!] 15MB 초과 — 아티팩트 게시 한도(16MB)에 근접")


if __name__ == '__main__':
    main()
