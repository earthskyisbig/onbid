#!/usr/bin/env python3
"""
압류재산 스냅샷(snapshot_market.py 출력)을 "공매 유성우" 시각화 HTML 로 만든다.

    python3 scripts/build_meteor.py                                  # _workspace/market_snapshot.json → _workspace/meteor.html
    python3 scripts/build_meteor.py --input x.json --output y.html
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORKSPACE  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / 'templates' / 'meteor.html'


def compact(snapshot: dict) -> dict:
    """
    페이지 내장용 압축. 물건 = [id, name, sido, sgg, usageM, usageS, apsl, usbdNft, rounds]
    rounds = [nsq, bgn, end, price, nsq, bgn, end, price, ...] (bgn/end 는 YYYYMMDDHHMM 정수, 취소회차 제외)
    """
    props = []
    for p in snapshot.get('properties', []):
        if not p.get('apsl') or not p.get('rounds'):
            continue
        if p.get('usageL') and p['usageL'] != '부동산':   # 압수물(동산·자동차·권리) 제외
            continue
        flat = []
        for r in p['rounds']:
            if not r.get('price') or r.get('stat') == '0012' or not r.get('bgn') or not r.get('end'):
                continue
            try:
                flat += [str(r['nsq']), int(r['bgn']), int(r['end']), int(r['price'])]
            except (TypeError, ValueError):
                continue
        if not flat:
            continue
        props.append([p['id'], p.get('name', ''), p.get('sido', ''), p.get('sgg', ''), p.get('usageM', ''),
                      p.get('usageS', ''), int(p['apsl']), int(p.get('usbdNft') or 0), flat])
    return {'snapshot_at': snapshot.get('snapshot_at'), 'pbanc_count': snapshot.get('pbanc_count'),
            'source': snapshot.get('source'), 'fields': ['id', 'name', 'sido', 'sgg', 'usageM', 'usageS', 'apsl', 'usbdNft', 'rounds[nsq,bgn,end,price]*'],
            'properties': props}


def build(inp: Path, out: Path) -> Path:
    data = compact(json.loads(inp.read_text(encoding='utf-8')))
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</script', '<\\/script')
    html = TEMPLATE.read_text(encoding='utf-8').replace('__METEOR_DATA__', payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding='utf-8')
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description='공매 유성우 시각화 생성')
    p.add_argument('--input', default=str(WORKSPACE / 'market_snapshot.json'))
    p.add_argument('--output', default=str(WORKSPACE / 'meteor.html'))
    args = p.parse_args(argv)
    out = build(Path(args.input), Path(args.output))
    print(f"저장: {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == '__main__':
    main()
