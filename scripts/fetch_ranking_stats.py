#!/usr/bin/env python3
"""
온비드 순위물건목록 / 물건목록 / 입찰결과상세 / 용도별 입찰통계 조회 스크립트
(2026-07-26 활용신청 승인된 6개 신규 API, 실제 호출로 오퍼레이션명·파라미터 검증 완료)

서브커맨드:
    inq-rank        조회수 순위      (OnbidInqRnkClgSrvc/getInqRnkClg)
    interest-rank   관심물건 순위    (OnbidItrsCltrRnkClgSrvc/getItrsCltrRnkClg)
    discount-rank    저감률 순위      (Onbid50PctDecrCltrSrvc/get50PctDecrCltr)
    rlst-list       부동산 물건목록  (OnbidRlstListSrvc2/getRlstCltrList2)
    bid-result      물건 입찰결과상세 (OnbidCltrBidRsltDtlSrvc2/getCltrBidRsltDtl2)
    usg-stats       용도별 입찰통계  (OnbidUsgBidStatsSrvc/getKamcoCltrUsgStats, getOrgCltrUsgStats)

사용법:
    python3 fetch_ranking_stats.py inq-rank --cltr-div 부동산
    python3 fetch_ranking_stats.py interest-rank --cltr-div 부동산
    python3 fetch_ranking_stats.py discount-rank --cltr-div 부동산
    python3 fetch_ranking_stats.py rlst-list --prpt-div 0007 --pvct-trgt N
    python3 fetch_ranking_stats.py bid-result --cltr-mng-no 2024-1100-084555
    python3 fetch_ranking_stats.py usg-stats --scope kamco --stats-type 0044 --period 2024
    python3 fetch_ranking_stats.py usg-stats --scope org --period 2024
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ONBID_BASE as BASE, get_key, parse_onbid_response  # noqa: E402

KEY = get_key('ONBID_API_KEY', required=False)

CLTR_DIV_CHOICES = ['부동산', '동산', '자동차']


def call(svc, op, params, rows=10):
    p = {
        'serviceKey': KEY,
        'pageNo': 1,
        'numOfRows': rows,
        'resultType': 'json',
        **params,
    }
    r = requests.get(f"{BASE}/{svc}/{op}", params=p, timeout=15)
    r.raise_for_status()
    return parse_onbid_response(r.json())


def cmd_rank(args, svc, op, label):
    items, err = call(svc, op, {'cltrDivNm': args.cltr_div}, rows=args.rows)
    if err:
        print(f"[!] {label} 조회 실패: {err}")
        return
    print(f"\n{'순위':>3} {'물건관리번호':18} {'물건명':30} {'최저입찰가':>14} {'감정가':>14}")
    print('-' * 90)
    for it in items:
        print(f"  {it.get('sn',''):>2} {it.get('cltrMngNo',''):18} "
              f"{(it.get('onbidCltrNm') or '')[:28]:30} "
              f"{int(it.get('lowstBidPrcIndctCont') or 0):>14,} "
              f"{int(it.get('apslEvlAmt') or 0):>14,}")
    save(args, items, label)


def cmd_rlst_list(args):
    params = {'prptDivCd': args.prpt_div, 'pvctTrgtYn': args.pvct_trgt}
    if args.region_sido:
        params['lctnSdnm'] = args.region_sido
    if args.region_sggu:
        params['lctnSggnm'] = args.region_sggu
    items, err = call('OnbidRlstListSrvc2', 'getRlstCltrList2', params, rows=args.rows)
    if err:
        print(f"[!] 부동산 물건목록 조회 실패: {err}")
        return
    print(f"\n조회 결과: {len(items)}건")
    for it in items[:args.rows]:
        print(f"  {it.get('cltrMngNo',''):18} {(it.get('onbidCltrNm') or '')[:40]:40} "
              f"{it.get('lctnSdnm','')} {it.get('lctnSggnm','')}")
    save(args, items, 'rlst-list')


def cmd_bid_result(args):
    params = {'cltrMngNo': args.cltr_mng_no}
    if args.pbct_cdtn_no:
        params['pbctCdtnNo'] = args.pbct_cdtn_no
    items, err = call('OnbidCltrBidRsltDtlSrvc2', 'getCltrBidRsltDtl2', params, rows=args.rows)
    if err:
        print(f"[!] 입찰결과상세 조회 실패: {err}")
        return
    for it in items:
        print(json.dumps(it, ensure_ascii=False, indent=2))
    save(args, items, 'bid-result')


def cmd_usg_stats(args):
    if args.scope == 'kamco':
        if not args.stats_type:
            print("[!] --stats-type 필요 (0041:압류재산, 0044:국유재산, 0045:수탁/유입자산, 0046:공유재산)")
            return
        items, err = call('OnbidUsgBidStatsSrvc', 'getKamcoCltrUsgStats',
                           {'statsTypeCd': args.stats_type, 'inqPerd': args.period}, rows=args.rows)
    else:
        items, err = call('OnbidUsgBidStatsSrvc', 'getOrgCltrUsgStats',
                           {'inqPerd': args.period}, rows=args.rows)
    if err:
        print(f"[!] 용도별 입찰통계 조회 실패: {err}")
        return
    print(f"\n{'용도':20} {'입찰건수':>8} {'낙찰건수':>8} {'낙찰율%':>8} {'경쟁률':>10} {'낙찰가율%':>10}")
    print('-' * 75)
    for it in items:
        print(f"  {(it.get('clsCdNm') or '')[:18]:20} "
              f"{it.get('pbctCltrCnt',0):>8} {it.get('mtSumCnt',0):>8} "
              f"{it.get('scbrt',0):>8} {it.get('compRate',''):>10} "
              f"{it.get('scfbAmtRto1',0):>10}")
    save(args, items, f'usg-stats-{args.scope}')


def save(args, items, label):
    if not args.output:
        return
    out = {
        'query_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'label': label,
        'count': len(items),
        'items': items,
    }
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {args.output}")


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--output', help='JSON 저장 경로 (생략 시 저장 안 함)')
    common.add_argument('--rows', type=int, default=10, help='조회 건수 (기본 10)')

    parser = argparse.ArgumentParser(description='온비드 순위/목록/통계 조회', parents=[common])
    sub = parser.add_subparsers(dest='command', required=True)

    p1 = sub.add_parser('inq-rank', help='조회수 순위', parents=[common])
    p1.add_argument('--cltr-div', choices=CLTR_DIV_CHOICES, default='부동산')

    p2 = sub.add_parser('interest-rank', help='관심물건 순위', parents=[common])
    p2.add_argument('--cltr-div', choices=CLTR_DIV_CHOICES, default='부동산')

    p3 = sub.add_parser('discount-rank', help='저감률 순위', parents=[common])
    p3.add_argument('--cltr-div', choices=CLTR_DIV_CHOICES, default='부동산')

    p4 = sub.add_parser('rlst-list', help='부동산 물건목록 (입찰중/입찰예정)', parents=[common])
    p4.add_argument('--prpt-div', required=True,
                     help='재산유형코드, 복수는 쉼표구분 (0007:압류재산 0010:국유재산 0005:기타일반재산 '
                          '0004:불용품 0002:공유재산 0003:금융권담보재산 0006:유입재산 0008:수탁재산 '
                          '0011:공공개발재산 0013:파산재산)')
    p4.add_argument('--pvct-trgt', choices=['Y', 'N'], required=True, help='수의계약가능여부')
    p4.add_argument('--region-sido', help='소재지 시도')
    p4.add_argument('--region-sggu', help='소재지 시군구')

    p5 = sub.add_parser('bid-result', help='물건 입찰결과상세', parents=[common])
    p5.add_argument('--cltr-mng-no', required=True, help='물건관리번호 (예: 2024-1100-084555)')
    p5.add_argument('--pbct-cdtn-no', help='공매조건번호 (옵션)')

    p6 = sub.add_parser('usg-stats', help='용도별 입찰통계', parents=[common])
    p6.add_argument('--scope', choices=['kamco', 'org'], required=True,
                     help='kamco=캠코 물건, org=이용기관 물건')
    p6.add_argument('--stats-type', help='재산유형 통계유형코드 (kamco 필수: 0041/0044/0045/0046)')
    p6.add_argument('--period', required=True,
                     help='조회기간 (연도:2024, 월별:202403, 분기별:2024-1)')

    args = parser.parse_args()

    if not KEY:
        print("[!] ONBID_API_KEY가 비어있습니다. .env 확인 필요.")
        return

    if args.command == 'inq-rank':
        cmd_rank(args, 'OnbidInqRnkClgSrvc', 'getInqRnkClg', '조회수 순위')
    elif args.command == 'interest-rank':
        cmd_rank(args, 'OnbidItrsCltrRnkClgSrvc', 'getItrsCltrRnkClg', '관심물건 순위')
    elif args.command == 'discount-rank':
        cmd_rank(args, 'Onbid50PctDecrCltrSrvc', 'get50PctDecrCltr', '저감률 순위')
    elif args.command == 'rlst-list':
        cmd_rlst_list(args)
    elif args.command == 'bid-result':
        cmd_bid_result(args)
    elif args.command == 'usg-stats':
        cmd_usg_stats(args)


if __name__ == '__main__':
    main()
