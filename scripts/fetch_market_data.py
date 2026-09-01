#!/usr/bin/env python3
"""
국토교통부 실거래가 조회 스크립트 (molit-market-data 스킬 구현체)

--kind 로 물건 종류를 고른다 (전부 활용신청 승인 확인, 2026-09-02):
    apt    아파트            RTMSDataSvcAptTradeDev(+AptTrade 폴백) / AptRent      단지명 aptNm, 전용 excluUseAr
    offi   오피스텔          RTMSDataSvcOffiTrade / OffiRent                       단지명 offiNm, 전용 excluUseAr
    rh     연립·다세대       RTMSDataSvcRHTrade / RHRent                           건물명 mhouseNm, 전용 excluUseAr
    sh     단독·다가구       RTMSDataSvcSHTrade / SHRent                           읍면동 umdNm 매칭, 연면적 totalFloorAr
    land   토지              RTMSDataSvcLandTrade (전월세 없음)                     읍면동 umdNm 매칭, 면적 dealArea, ㎡당가
    shop   상업·업무용       RTMSDataSvcNrgTrade (전월세 없음)                      읍면동+건물용도 매칭, 면적 buildingAr, ㎡당가
응답은 XML 전용.

사용법:
    python3 scripts/fetch_market_data.py --keyword 덕계역금강펜테리움 --lawd-cd 41630 --area 59.3 \\
        --apsl 339000000 --low-bid 305100000 --cltr-mng-no 2026-0200-106923
    python3 scripts/fetch_market_data.py --kind rh --keyword 호안빌 --lawd-cd "서울 은평구" --area 39.94
    python3 scripts/fetch_market_data.py --kind land --keyword 검천리 --lawd-cd 41610 --area 500 --area-tol 300
    python3 scripts/fetch_market_data.py --batch targets.json     # [{"cltr_mng_no","kind","keyword","lawd_cd","area","apsl","low_bid"}]

    옵션: --months 12 / --area-tol 5 (0건이면 ±10 → 24개월 자동 확장, --no-expand 로 끔) / --output 경로

모든 금액 입력·출력은 원(₩) 단위. 표시용 *_억 필드를 함께 기록한다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MOLIT_BASE, WORKSPACE, format_price, get_key  # noqa: E402

# 종류별 엔드포인트·필드 (trade 는 순서대로 시도, 앞이 실패하면 다음)
KINDS = {
    'apt':  {'label': '아파트', 'trade': ['RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev',
                                          'RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade'],
             'rent': 'RTMSDataSvcAptRent/getRTMSDataSvcAptRent',
             'name': 'aptNm', 'area': 'excluUseAr', 'match': ['aptNm']},
    'offi': {'label': '오피스텔', 'trade': ['RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade'],
             'rent': 'RTMSDataSvcOffiRent/getRTMSDataSvcOffiRent',
             'name': 'offiNm', 'area': 'excluUseAr', 'match': ['offiNm']},
    'rh':   {'label': '연립다세대', 'trade': ['RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade'],
             'rent': 'RTMSDataSvcRHRent/getRTMSDataSvcRHRent',
             'name': 'mhouseNm', 'area': 'excluUseAr', 'match': ['mhouseNm']},
    'sh':   {'label': '단독다가구', 'trade': ['RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade'],
             'rent': 'RTMSDataSvcSHRent/getRTMSDataSvcSHRent',
             'name': 'umdNm', 'area': 'totalFloorAr', 'match': ['umdNm', 'houseType']},
    'land': {'label': '토지', 'trade': ['RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade'],
             'rent': None, 'name': 'umdNm', 'area': 'dealArea', 'match': ['umdNm', 'jimok', 'landUse'],
             'per_sqm': True},
    'shop': {'label': '상업업무용', 'trade': ['RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade'],
             'rent': None, 'name': 'umdNm', 'area': 'buildingAr',
             'match': ['umdNm', 'buildingUse', 'buildingType'], 'per_sqm': True},
}
EXTRA_TAGS = ('floor', 'buildYear', 'umdNm', 'jibun', 'dealingGbn', 'cdealType', 'houseType',
              'jimok', 'landUse', 'buildingUse', 'buildingType', 'plottageAr', 'landAr', 'shareDealingType')

# 경기·서울 주요 법정동코드 (앞 5자리). 없으면 www.code.go.kr 에서 확인
LAWD_CD = {
    '수원 장안구': '41110', '수원 권선구': '41113', '수원 팔달구': '41115', '수원 영통구': '41117',
    '성남 수정구': '41131', '성남 중원구': '41133', '성남 분당구': '41135',
    '의정부': '41150', '안양 만안구': '41171', '안양 동안구': '41173', '부천': '41190',
    '광명': '41210', '평택': '41220', '동두천': '41250', '안산 상록구': '41271', '안산 단원구': '41273',
    '고양 덕양구': '41281', '고양 일산동구': '41285', '고양 일산서구': '41287', '과천': '41290',
    '구리': '41310', '남양주': '41360', '오산': '41370', '시흥': '41390', '군포': '41410',
    '의왕': '41430', '하남': '41450', '용인 처인구': '41461', '용인 기흥구': '41463', '용인 수지구': '41465',
    '파주': '41480', '이천': '41500', '안성': '41550', '김포': '41570', '화성': '41590',
    '광주': '41610', '양주': '41630', '포천': '41650', '여주': '41670', '양평': '41830', '가평': '41820',
    '서울 종로구': '11110', '서울 중구': '11140', '서울 용산구': '11170', '서울 성동구': '11200',
    '서울 광진구': '11215', '서울 동대문구': '11230', '서울 중랑구': '11260', '서울 성북구': '11290',
    '서울 강북구': '11305', '서울 도봉구': '11320', '서울 노원구': '11350', '서울 은평구': '11380',
    '서울 서대문구': '11410', '서울 마포구': '11440', '서울 양천구': '11470', '서울 강서구': '11500',
    '서울 구로구': '11530', '서울 금천구': '11545', '서울 영등포구': '11560', '서울 동작구': '11590',
    '서울 관악구': '11620', '서울 서초구': '11650', '서울 강남구': '11680', '서울 송파구': '11710',
    '서울 강동구': '11740',
}


def recent_months(n: int = 12, base: datetime | None = None) -> list[str]:
    """이번 달부터 n개월 (YYYYMM, 최신 → 과거 순)"""
    dt = (base or datetime.now()).replace(day=1)
    out = []
    for _ in range(n):
        out.append(dt.strftime('%Y%m'))
        dt = (dt - timedelta(days=1)).replace(day=1)
    return out


def parse_xml(xml_text: str):
    """(items, error). resultCode 가 00/000 이 아니면 error 문자열."""
    if not xml_text or not xml_text.strip():
        return [], '빈 응답'
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return [], f'XML 파싱 오류: {e} / {xml_text[:120]}'
    rc_el = root.find('.//resultCode')
    rc = (rc_el.text or '').strip() if rc_el is not None else '00'
    if rc not in ('00', '000', ''):
        msg_el = root.find('.//resultMsg')
        return [], f"API 오류 {rc}: {(msg_el.text if msg_el is not None else '')}"
    return root.findall('.//item'), None


def get_text(item, tag: str) -> str:
    el = item.find(tag)
    return el.text.strip() if el is not None and el.text else ''


def _amount_won(s: str):
    """'33,500' (만원) → 335000000 (원)"""
    s = (s or '').replace(',', '').strip()
    return int(s) * 10_000 if s.isdigit() else None


def _float(s: str, default=0.0) -> float:
    try:
        return float((s or '').replace(',', '')) if s else default
    except ValueError:
        return default


def fetch_xml(url: str, key: str, lawd_cd: str, deal_ymd: str, timeout: int = 15) -> str:
    r = requests.get(url, params={'serviceKey': key, 'LAWD_CD': lawd_cd, 'DEAL_YMD': deal_ymd,
                                  'pageNo': 1, 'numOfRows': 1000}, timeout=timeout)
    return r.text if r.status_code == 200 else ''


def fetch_trade(key, lawd_cd, deal_ymd, kind: str = 'apt'):
    err = None
    for path in KINDS[kind]['trade']:
        items, err = parse_xml(fetch_xml(f"{MOLIT_BASE}/{path}", key, lawd_cd, deal_ymd))
        if not err:
            return items, None
    return [], err


def fetch_rent(key, lawd_cd, deal_ymd, kind: str = 'apt'):
    path = KINDS[kind]['rent']
    if not path:
        return [], None
    return parse_xml(fetch_xml(f"{MOLIT_BASE}/{path}", key, lawd_cd, deal_ymd))


def _deal_date(item) -> str:
    return f"{get_text(item, 'dealYear')}-{get_text(item, 'dealMonth').zfill(2)}-{get_text(item, 'dealDay').zfill(2)}"


def match(item, keyword: str, target_area: float, area_tol: float, kind: str = 'apt') -> bool:
    cfg = KINDS[kind]
    if keyword:
        hay = ' '.join(get_text(item, t) for t in cfg['match'])
        if keyword not in hay:
            return False
    if target_area:
        ar = _float(get_text(item, cfg['area']))
        if abs(ar - target_area) > area_tol:
            return False
    return True


def _record_trade(it, kind: str) -> dict:
    cfg = KINDS[kind]
    amt = _amount_won(get_text(it, 'dealAmount'))
    area = _float(get_text(it, cfg['area']))
    rec = {'name': get_text(it, cfg['name']), 'area': area,
           'dealAmount': amt, 'dealAmount_억': round(amt / 1e8, 3) if amt else None,
           'dealYMD': _deal_date(it)}
    if cfg.get('per_sqm') and amt and area:
        rec['price_per_sqm'] = round(amt / area)
    for t in EXTRA_TAGS:
        v = get_text(it, t)
        if v:
            rec[t] = v
    if kind == 'apt':
        rec['aptNm'] = rec['name']   # 하위 호환
    return rec


def _record_rent(it, kind: str) -> dict:
    cfg = KINDS[kind]
    monthly = get_text(it, 'monthlyRent').replace(',', '')
    dep = _amount_won(get_text(it, 'deposit'))
    rec = {'name': get_text(it, cfg['name']), 'area': _float(get_text(it, cfg['area'])),
           'type': '월세' if monthly and monthly != '0' else '전세',
           'deposit': dep, 'deposit_억': round(dep / 1e8, 3) if dep else None,
           'monthlyRent': int(monthly) * 10_000 if monthly.isdigit() else 0,
           'dealYMD': _deal_date(it), 'contractTerm': get_text(it, 'contractTerm')}
    for t in ('floor', 'buildYear', 'umdNm', 'houseType', 'contractType'):
        v = get_text(it, t)
        if v:
            rec[t] = v
    if kind == 'apt':
        rec['aptNm'] = rec['name']
    return rec


def query_apt(key: str, keyword: str, lawd_cd: str, target_area: float,
              months: int = 12, area_tol: float = 5.0, sleep: float = 0.2, verbose: bool = True,
              kind: str = 'apt'):
    """단일 대상 매매+전월세 조회. 반환: (trade_list, rent_list, errors). 이름은 하위 호환용 (모든 kind 지원)."""
    trade, rent, errors = [], [], []
    for ym in recent_months(months):
        time.sleep(sleep)
        t_items, t_err = fetch_trade(key, lawd_cd, ym, kind)
        if t_err:
            errors.append({'month': ym, 'api': 'trade', 'error': t_err})
        trade += [_record_trade(it, kind) for it in t_items if match(it, keyword, target_area, area_tol, kind)]
        r_items, r_err = fetch_rent(key, lawd_cd, ym, kind)
        if r_err:
            errors.append({'month': ym, 'api': 'rent', 'error': r_err})
        rent += [_record_rent(it, kind) for it in r_items if match(it, keyword, target_area, area_tol, kind)]
    cancelled = [t for t in trade if t.get('cdealType') == 'O']   # 계약해제 건 제외
    trade = [t for t in trade if t.get('cdealType') != 'O']
    if verbose and cancelled:
        print(f"  (계약해제 {len(cancelled)}건 제외)")
    return trade, rent, errors


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def summarize(trade, rent, apsl_amt=None, low_bid=None, target_area: float | None = None) -> dict:
    amts = [t['dealAmount'] for t in trade if t.get('dealAmount')]
    jeonse = [r['deposit'] for r in rent if r['type'] == '전세' and r.get('deposit')]
    wolse = [r for r in rent if r['type'] == '월세']
    s = {
        'trade_count': len(trade),
        'trade_avg': round(sum(amts) / len(amts)) if amts else None,
        'trade_median': round(_median(amts)) if amts else None,
        'trade_max': max(amts) if amts else None,
        'trade_min': min(amts) if amts else None,
        'trade_latest': max(trade, key=lambda t: t['dealYMD'])['dealYMD'] if trade else None,
        'jeonse_count': len(jeonse),
        'jeonse_avg': round(sum(jeonse) / len(jeonse)) if jeonse else None,
        'wolse_count': len(wolse),
        'build_year': next((t['buildYear'] for t in trade + rent if t.get('buildYear')), None),
    }
    per = [t['price_per_sqm'] for t in trade if t.get('price_per_sqm')]
    if per:
        s['price_per_sqm_avg'] = round(sum(per) / len(per))
        s['price_per_sqm_median'] = round(_median(per))
        if target_area:
            s['implied_value_at_target_area'] = round(s['price_per_sqm_median'] * target_area)
    for k in ('trade_avg', 'trade_median', 'trade_max', 'trade_min', 'jeonse_avg'):
        s[f'{k}_억'] = round(s[k] / 1e8, 3) if s[k] else None
    if s['trade_avg'] and s['jeonse_avg']:
        s['jeonse_ratio_pct'] = round(s['jeonse_avg'] / s['trade_avg'] * 100, 1)
    ref = s.get('implied_value_at_target_area') or s['trade_avg']
    if apsl_amt and ref:
        s['vs_apsl'] = ref - apsl_amt
        s['vs_apsl_pct'] = round(s['vs_apsl'] / apsl_amt * 100, 1)
    if low_bid and ref:
        s['vs_lowbid'] = ref - low_bid
        s['vs_lowbid_pct'] = round(s['vs_lowbid'] / low_bid * 100, 1)
    if s['trade_count'] == 0:
        s['liquidity_flag'] = '거래 0건 — 유동성 위험'
    elif s['trade_count'] < 3:
        s['liquidity_flag'] = '거래 3건 미만 — 통계 신뢰 부족'
    else:
        s['liquidity_flag'] = 'OK'
    return s


def run_one(key: str, keyword: str, lawd_cd: str, area: float, apsl=None, low_bid=None,
            months: int = 12, area_tol: float = 5.0, expand: bool = True, verbose: bool = True,
            kind: str = 'apt') -> dict:
    """SKILL Step 3 규칙: ±tol·months → ±max(tol,10) → 24개월 순으로 확장."""
    attempts = [(months, area_tol)]
    if expand:
        attempts += [(months, max(area_tol, 10.0)), (max(months, 24), max(area_tol, 10.0))]
    trade, rent, errors, used = [], [], [], attempts[0]
    for m, tol in attempts:
        used = (m, tol)
        if verbose:
            print(f"  조회[{KINDS[kind]['label']}]: {keyword or '(전체)'} / {lawd_cd} / {area}㎡ ±{tol} / 최근 {m}개월")
        trade, rent, errors = query_apt(key, keyword, lawd_cd, area, months=m, area_tol=tol,
                                        verbose=verbose, kind=kind)
        if trade or rent:
            break
    summary = summarize(trade, rent, apsl, low_bid, target_area=area if KINDS[kind].get('per_sqm') else None)
    return {
        'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'kind': kind, 'kind_label': KINDS[kind]['label'],
        'apt_keyword': keyword, 'lawd_cd': lawd_cd, 'target_area': area,
        'apsl_amt': apsl, 'low_bid': low_bid,
        'query_months': used[0], 'area_tol': used[1],
        'period': f"{recent_months(used[0])[-1]} ~ {recent_months(used[0])[0]}",
        'summary': summary, 'trade': trade, 'rent': rent, 'errors': errors,
    }


def print_summary(res: dict):
    s = res['summary']
    print(f"\n[시세 분석·{res.get('kind_label', '')}] {res['apt_keyword']} {res['target_area']}㎡ "
          f"(LAWD_CD {res['lawd_cd']}) 기간 {res['period']} (±{res['area_tol']}㎡)")
    if s['trade_count']:
        print(f"  매매 {s['trade_count']}건 | 평균 {format_price(s['trade_avg'])} | 중앙 {format_price(s['trade_median'])} "
              f"| 최고 {format_price(s['trade_max'])} | 최저 {format_price(s['trade_min'])} | 최근 {s['trade_latest']}")
        if s.get('price_per_sqm_median'):
            print(f"  ㎡당 중앙값 {s['price_per_sqm_median']:,}원"
                  + (f" → 대상 면적 환산 {format_price(s['implied_value_at_target_area'])}" if s.get('implied_value_at_target_area') else ''))
    else:
        print("  매매 0건")
    if KINDS[res.get('kind', 'apt')]['rent']:
        print(f"  전세 {s['jeonse_count']}건 | 평균 {format_price(s['jeonse_avg'])} | 월세 {s['wolse_count']}건"
              + (f" | 전세가율 {s['jeonse_ratio_pct']}%" if s.get('jeonse_ratio_pct') else ''))
    if s.get('vs_apsl_pct') is not None:
        print(f"  시세 vs 감정가: {format_price(s['vs_apsl'])} ({s['vs_apsl_pct']:+.1f}%)")
    if s.get('vs_lowbid_pct') is not None:
        print(f"  시세 vs 최저가: {format_price(s['vs_lowbid'])} ({s['vs_lowbid_pct']:+.1f}%)")
    if s['liquidity_flag'] != 'OK':
        print(f"  ⚠️ {s['liquidity_flag']}")
    if res['errors']:
        print(f"  API 오류 {len(res['errors'])}건: {res['errors'][0]}")


def resolve_lawd(v: str) -> str | None:
    lawd = LAWD_CD.get(v, v)
    return lawd if (lawd.isdigit() and len(lawd) == 5) else None


def main(argv=None):
    p = argparse.ArgumentParser(description='국토부 실거래가 조회 (아파트/오피스텔/연립다세대/단독/토지/상업용)')
    p.add_argument('--kind', choices=list(KINDS), default='apt', help='물건 종류 (기본 apt)')
    p.add_argument('--keyword', default='', help='단지명·건물명 키워드 (land/sh 는 읍면동명, shop 은 읍면동 또는 건물용도)')
    p.add_argument('--lawd-cd', help='법정동코드 앞 5자리 (또는 "양주", "수원 권선구" 같은 지역명)')
    p.add_argument('--area', type=float, default=0, help='면적 ㎡ (0이면 면적 필터 없음)')
    p.add_argument('--apsl', type=float, help='감정가 (원)')
    p.add_argument('--low-bid', type=float, help='최저입찰가 (원)')
    p.add_argument('--cltr-mng-no', help='물건관리번호 (출력 파일명용)')
    p.add_argument('--months', type=int, default=12)
    p.add_argument('--area-tol', type=float, default=5.0)
    p.add_argument('--no-expand', action='store_true', help='0건일 때 자동 확장 안 함')
    p.add_argument('--batch', help='복수 물건 JSON 파일 경로')
    p.add_argument('--output', help='저장 경로 (기본 _workspace/market_{cltrMngNo}.json)')
    args = p.parse_args(argv)

    key = get_key('MOLIT_API_KEY')

    if args.batch:
        targets = json.load(open(args.batch, encoding='utf-8'))
        results = {}
        for t in targets:
            cid = t.get('cltr_mng_no') or t.get('keyword')
            lawd = resolve_lawd(str(t['lawd_cd']))
            if not lawd:
                results[cid] = {'error': f"법정동코드 불명: {t['lawd_cd']}"}
                continue
            res = run_one(key, t.get('keyword', ''), lawd, float(t.get('area') or 0),
                          t.get('apsl'), t.get('low_bid'), months=args.months, area_tol=args.area_tol,
                          expand=not args.no_expand, kind=t.get('kind', args.kind))
            res['cltrMngNo'] = t.get('cltr_mng_no')
            print_summary(res)
            results[cid] = res
        out = Path(args.output or WORKSPACE / f"market_data_{datetime.now():%Y%m%d}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"\n저장: {out}")
        return

    if not args.lawd_cd:
        p.error('--lawd-cd 가 필요합니다 (또는 --batch)')
    lawd = resolve_lawd(args.lawd_cd)
    if not lawd:
        p.error(f'법정동코드를 알 수 없습니다: {args.lawd_cd} (5자리 숫자 또는 LAWD_CD 표의 지역명)')

    res = run_one(key, args.keyword, lawd, args.area, args.apsl, args.low_bid,
                  months=args.months, area_tol=args.area_tol, expand=not args.no_expand, kind=args.kind)
    res['cltrMngNo'] = args.cltr_mng_no
    print_summary(res)
    out = Path(args.output or WORKSPACE / f"market_{args.cltr_mng_no or args.keyword or args.kind}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  저장: {out}")


if __name__ == '__main__':
    main()
