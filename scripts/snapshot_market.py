#!/usr/bin/env python3
"""
압류재산 전체 스냅샷: 공고목록(getPbancList2) → 공고별 물건·회차(getPbancCltrInf2) 전수 수집.

    python3 scripts/snapshot_market.py                    # → _workspace/market_snapshot.json (약 360 공고 × 1초 ≈ 6~7분)
    python3 scripts/snapshot_market.py --max-pbanc 50 --output x.json

출력: 물건별 {cltrMngNo, name, addr, sido, sgg, usageL/M/S, apsl, usbdNft, rounds:[{nsq, cdtn, bgn, end, price, stat}]}
용도: 대시보드·시각화(build_meteor.py)·시장 통계. 개별 분석은 search_properties.py 를 쓴다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORKSPACE, get_key, onbid_get, to_float, to_int  # noqa: E402
from search_properties import call_list_api  # noqa: E402

SIDO_SHORT = {'서울특별시': '서울', '부산광역시': '부산', '대구광역시': '대구', '인천광역시': '인천', '광주광역시': '광주',
              '대전광역시': '대전', '울산광역시': '울산', '세종특별자치시': '세종', '경기도': '경기', '강원특별자치도': '강원',
              '강원도': '강원', '충청북도': '충북', '충청남도': '충남', '전북특별자치도': '전북', '전라북도': '전북',
              '전라남도': '전남', '경상북도': '경북', '경상남도': '경남', '제주특별자치도': '제주'}


def split_addr(addr: str):
    parts = (addr or '').split()
    sido = parts[0] if parts else ''
    sgg = parts[1] if len(parts) > 1 and not parts[1].startswith('*') else ''
    return SIDO_SHORT.get(sido, sido[:2] if sido else '기타'), sgg


def fetch_items(pbanc_no: str, key: str):
    items, page = [], 1
    while True:
        chunk, err = onbid_get('OnbidPbancCltrDtlSrvc2', 'getPbancCltrInf2', {'pbancMngNo': pbanc_no},
                               rows=500, page=page, timeout=20, key=key)
        if err:
            return items, err
        items += chunk
        if len(chunk) < 500:
            return items, None
        page += 1
        time.sleep(0.5)


def main(argv=None):
    p = argparse.ArgumentParser(description='압류재산 전체 스냅샷')
    p.add_argument('--max-pbanc', type=int, default=None)
    p.add_argument('--output', default=str(WORKSPACE / 'market_snapshot.json'))
    p.add_argument('--sleep', type=float, default=1.0)
    args = p.parse_args(argv)
    key = get_key('ONBID_API_KEY')

    print('[1] 공고목록 수집...')
    pbancs, err = call_list_api(key=key)
    if err:
        sys.exit(f'[!] {err}')
    if args.max_pbanc:
        pbancs = pbancs[:args.max_pbanc]
    print(f'    고유 공고 {len(pbancs)}건')

    props: dict[str, dict] = {}
    errors = []
    t0 = time.time()
    for i, e in enumerate(pbancs, 1):
        time.sleep(args.sleep)
        items, err = fetch_items(e['pbancMngNo'], key)
        if err:
            errors.append({'pbancMngNo': e['pbancMngNo'], 'error': err})
        for it in items:
            cid = it.get('cltrMngNo')
            if not cid:
                continue
            if cid not in props:
                sido, sgg = split_addr(it.get('cltrAdr') or it.get('onbidCltrNm') or '')
                props[cid] = {
                    'id': cid, 'pbanc': e['pbancMngNo'],
                    'name': it.get('onbidCltrNm') or '', 'addr': it.get('cltrAdr') or '',
                    'sido': sido, 'sgg': sgg,
                    'usageL': it.get('cltrUsgLclsCtgrNm') or '', 'usageM': it.get('cltrUsgMclsCtgrNm') or '',
                    'usageS': it.get('cltrUsgSclsCtgrNm') or '',
                    'apsl': to_float(it.get('apslEvlAmt'), None), 'usbdNft': to_int(it.get('usbdNft')),
                    'rounds': [],
                }
            props[cid]['rounds'].append({
                'nsq': it.get('pbctNsq') or '', 'cdtn': it.get('pbctCdtnNo'),
                'bgn': it.get('cltrBidBgngDt') or '', 'end': it.get('cltrBidEndDt') or '',
                'price': to_float(it.get('lowstBidPrcIndctCont'), None), 'stat': it.get('pbctStatCd') or '',
            })
        if i % 20 == 0 or i == len(pbancs):
            el = time.time() - t0
            print(f'    {i}/{len(pbancs)} 공고 · 물건 {len(props)}건 · {el:.0f}s 경과 · 남은 예상 {el / i * (len(pbancs) - i):.0f}s')

    for pr in props.values():
        seen = set()
        uniq = []
        for r in sorted(pr['rounds'], key=lambda r: (r['bgn'], str(r['nsq']))):
            k = (r['cdtn'], r['bgn'])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(r)
        pr['rounds'] = uniq

    out = {
        'snapshot_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'source': 'OnbidPbancListSrvc2/getPbancList2 + OnbidPbancCltrDtlSrvc2/getPbancCltrInf2 (prptDivCd=0007)',
        'pbanc_count': len(pbancs), 'property_count': len(props),
        'properties': sorted(props.values(), key=lambda x: x['id']),
        'errors': errors,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    print(f'저장: {args.output} (물건 {len(props)}건, 오류 {len(errors)}건)')


if __name__ == '__main__':
    main()
