#!/usr/bin/env python3
"""
온비드 공매 물건 필터 검색 스크립트

사용법:
    python3 scripts/search_properties.py \
        --region "경기도 수원시" \
        --type 아파트 \
        --area-min 50 --area-max 120 \
        --price-max 500000000 \
        --min-fails 2

지원 필터:
    --region      지역 (시도 또는 "시도 시군구" 형식, 예: "경기도", "경기도 수원시")
    --type        용도 (아파트/토지/상가/오피스텔/임야/공장/창고 등 키워드)
    --area-min    면적 하한 (㎡)
    --area-max    면적 상한 (㎡)
    --price-min   최저입찰가 하한 (원)
    --price-max   최저입찰가 상한 (원)
    --min-fails   유찰횟수 최소
    --max-fails   유찰횟수 최대
    --status      입찰상태 (진행중/예정/모두, 기본: 모두)
    --ids         물건관리번호 목록 (공백 구분, 목록API 없이 직접 조회)
    --rows        상세조회 numOfRows (기본: 100 — 회차가 잘리지 않도록 충분히 크게)
    --max-pbanc   모드B에서 처리할 최대 공고 수 (기본: 100, 전체는 약 360건 ≈ 6분)

유찰횟수 필터 (2026-09-02 수정):
    공고목록의 pbancMngNo 반복 횟수는 "예약된 회차 수"이지 유찰 횟수가 아니다.
    --min-fails 는 단계2(getPbancCltrInf2)의 물건별 usbdNft 와 단계3 상세값으로만 적용한다.

회차 선택 원칙 (2026-07-26 버그 이후 고정):
    동일 cltrMngNo 의 여러 예약 회차 중 "입찰종료일시가 아직 지나지 않은 회차 가운데
    입찰시작일시가 가장 이른 회차"를 현재 회차로 채택한다. pbctNsq 최댓값은
    가장 먼 미래의 최다할인 회차이므로 절대 사용하지 않는다.
    전체 회차 일정은 결과의 `rounds` 배열에 그대로 남긴다 (저감 스케줄 참고용).

감정가 대비 비율 (2026-09-02 수정):
    API 의 apslPrcCtrsLowstBidRto 는 상세조회에서 null 로 오는 경우가 많아
    lowstBidPrc / apslEvlAmt 로 직접 계산한다 (API 값은 apslRatio_api 에 보존).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (WORKSPACE, format_price, get_key, onbid_get,  # noqa: E402
                    to_float, to_int)

OUTPUT = str(WORKSPACE / '01_search_results.json')

# 용도 키워드 → API 파라미터 매핑
PROPERTY_TYPE_MAP = {
    '아파트':     {'cltrUsgSclsCtgrNm': '아파트'},
    '연립':       {'cltrUsgSclsCtgrNm': '연립'},
    '다세대':     {'cltrUsgSclsCtgrNm': '다세대'},
    '단독주택':   {'cltrUsgSclsCtgrNm': '단독'},
    '오피스텔':   {'cltrUsgSclsCtgrNm': '오피스텔'},
    '상가':       {'cltrUsgSclsCtgrNm': '상가'},
    '상업용':     {'cltrUsgSclsCtgrNm': '상업'},
    '토지':       {'cltrUsgMclsCtgrNm': '토지'},
    '임야':       {'cltrUsgSclsCtgrNm': '임야'},
    '공장':       {'cltrUsgSclsCtgrNm': '공장'},
    '창고':       {'cltrUsgSclsCtgrNm': '창고'},
    '건물':       {'cltrUsgLclsCtgrNm': '건물'},
}

# 입찰상태 코드
STATUS_CODE = {
    '준비중': '0001',
    '진행중': '0002',
    '예정':   '0001',
    '모두':   '',
}

# pbctStatNm이 코드를 반환하는 API 버그 대응 (2026-06-24 확인)
STATUS_NAME = {
    '0001': '입찰준비중',
    '0002': '입찰진행중',
    '0003': '입찰마감',
    '0006': '개찰중',
    '0009': '수의계약가능',
    '0010': '낙찰',
    '0011': '유찰',
    '0012': '취소',
}

ROUND_FIELDS = ('pbctNsq', 'pbctCdtnNo', 'cltrBidBgngDt', 'cltrBidEndDt', 'pbctStatCd')


# ─────────────────────────── 회차 선택 ───────────────────────────
def _dt_key(item: dict, field: str, default: str = '9' * 12) -> str:
    v = str(item.get(field) or '')
    return v if v else default


def round_summary(item: dict) -> dict:
    """회차 일정 요약 (rounds 배열 원소)."""
    s = {k: item.get(k, '') for k in ROUND_FIELDS}
    s['lowstBidPrc'] = to_float(item.get('lowstBidPrcIndctCont') or item.get('lowstBidPrc'))
    return s


def select_current_round(items: list[dict], now: datetime | None = None) -> dict | None:
    """
    동일 물건의 회차 목록에서 현재 회차 1건을 고른다.
    1) 입찰종료일시(cltrBidEndDt)가 now 이후인 회차만 후보 (없으면 전체를 후보로)
    2) 후보 중 입찰시작일시(cltrBidBgngDt)가 가장 이른 회차
    """
    if not items:
        return None
    now_s = (now or datetime.now()).strftime('%Y%m%d%H%M')
    live = [it for it in items if _dt_key(it, 'cltrBidEndDt') >= now_s]
    pool = live or items
    return min(pool, key=lambda it: _dt_key(it, 'cltrBidBgngDt'))


def group_rounds(items: list[dict], key_field: str = 'cltrMngNo') -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for it in items:
        k = it.get(key_field)
        if k:
            groups.setdefault(k, []).append(it)
    return groups


# ─────────────────────────── API 단계 ───────────────────────────
def summarize_pbanc_list(all_items: list[dict]) -> list[dict]:
    """
    공고목록 원본(같은 pbancMngNo 가 회차마다 반복됨)을 고유 공고 목록으로 압축한다.
    최신 공고일(pbancYmd) 순. 각 항목에 list_count(목록 반복 횟수)와 pbctNsq_max 를 남긴다.

    ※ 반복 횟수는 유찰 횟수가 **아니다** (2026-09-02 실측: 359개 공고 중 253개가 10회 반복 —
      미리 예약된 회차 수. 2회만 등장한 공고의 물건이 실제 유찰 4~6회인 사례 다수).
      유찰 필터는 단계2의 usbdNft(물건별 실제값)로만 적용한다.
    """
    groups: dict[str, list[dict]] = {}
    for it in all_items:
        no = it.get('pbancMngNo')
        if no:
            groups.setdefault(no, []).append(it)
    out = []
    for no, rows in groups.items():
        out.append({
            'pbancMngNo': no,
            'list_count': len(rows),
            'pbctNsq_max': max((to_int(r.get('pbctNsq')) for r in rows), default=0),
            'pbancYmd': max((str(r.get('pbancYmd') or '') for r in rows), default=''),
            'pbancKindNm': rows[-1].get('pbancKindNm', ''),
            'onbidPbancNm': rows[-1].get('onbidPbancNm', ''),
        })
    out.sort(key=lambda e: e['pbancYmd'], reverse=True)
    return out


def call_list_api(key=None):
    """
    OnbidPbancListSrvc2/getPbancList2 공고목록 API 호출 (차세대).
    prptDivCd=0007(압류재산) 전체(약 3,000행/30페이지)를 수집해 고유 pbancMngNo 목록을 반환한다.
    유찰 횟수 필터는 여기서 하지 않는다 — summarize_pbanc_list 주석 참조.
    """
    all_items = []
    page = 1
    while True:
        items, err = onbid_get('OnbidPbancListSrvc2', 'getPbancList2',
                               {'prptDivCd': '0007', 'pvctTrgtYn': 'N'},
                               rows=100, page=page, timeout=15, key=key)
        if err:
            return None, err
        if not items:
            break
        all_items.extend(items)
        if len(items) < 100:
            break
        page += 1
        time.sleep(0.15)
    return summarize_pbanc_list(all_items), None


def _prefilter_pass(item: dict, pf: dict) -> bool:
    addr = item.get('cltrAdr', '') or ''
    usage = ' '.join(filter(None, [
        item.get('cltrUsgSclsCtgrNm', ''), item.get('cltrUsgMclsCtgrNm', ''),
        item.get('cltrUsgLclsCtgrNm', ''), item.get('onbidCltrNm', ''),
    ]))
    fails = to_int(item.get('usbdNft'))
    price = to_float(item.get('lowstBidPrcIndctCont'))
    if pf.get('sido') and pf['sido'] not in addr:
        return False
    if pf.get('sggu') and pf['sggu'] not in addr:
        return False
    if pf.get('type_kw') and pf['type_kw'] not in usage:
        return False
    if pf.get('min_fails') is not None and fails < pf['min_fails']:
        return False
    if pf.get('price_min') is not None and price < pf['price_min']:
        return False
    if pf.get('price_max') is not None and price > pf['price_max']:
        return False
    return True


def call_pbanc_cltr_api(pbanc_entries, pre_filter=None, key=None, now=None):
    """
    OnbidPbancCltrDtlSrvc2/getPbancCltrInf2 호출.
    공고관리번호(pbancMngNo) → 물건관리번호(cltrMngNo) 목록 변환.
    pre_filter 로 지역/용도/유찰/가격을 미리 걸러 단계3 호출 수를 줄인다.
    """
    cltr_nos: list[str] = []
    errors = []
    pf = pre_filter or {}
    for idx, entry in enumerate(pbanc_entries):
        no = entry.get('pbancMngNo') if isinstance(entry, dict) else entry
        time.sleep(1.0)
        if (idx + 1) % 20 == 0:
            print(f"    ...공고 {idx + 1}/{len(pbanc_entries)} 처리 중 (통과 {len(cltr_nos)}건)")
        items, err = onbid_get('OnbidPbancCltrDtlSrvc2', 'getPbancCltrInf2',
                               {'pbancMngNo': no}, rows=50, timeout=15, key=key)
        if err:
            errors.append({'pbancMngNo': no, 'error': err})
            continue
        for cn, rounds in group_rounds(items).items():
            if cn in cltr_nos:
                continue
            cur = select_current_round(rounds, now)
            if cur and _prefilter_pass(cur, pf):
                cltr_nos.append(cn)
    return cltr_nos, errors


def call_detail_api(cltr_mng_nos, rows=100, key=None):
    """
    OnbidRlstDtlSrvc2/getRlstDtlInf2 상세 API 배치 호출.
    한 물건의 모든 회차가 items 로 오므로 rows 를 충분히 크게 준다.
    """
    results = []
    errors = []
    for no in cltr_mng_nos:
        time.sleep(1.0)
        items, err = onbid_get('OnbidRlstDtlSrvc2', 'getRlstDtlInf2',
                               {'cltrMngNo': no}, rows=rows, timeout=20, key=key)
        if err:
            errors.append({'cltrMngNo': no, 'error': err})
            continue
        results.extend(items)
    return results, errors


# ─────────────────────────── 정규화 ───────────────────────────
def extract_area(item):
    """물건 면적 추출: bldSqms(건물) > landSqms(토지) > sqmsList 첫 항목"""
    for f in ('bldSqms', 'landSqms'):
        v = item.get(f)
        if v not in (None, ''):
            fv = to_float(v, None)
            if fv is not None:
                return fv
    sqms_list = item.get('sqmsList')
    if isinstance(sqms_list, list) and sqms_list and isinstance(sqms_list[0], dict):
        cont = sqms_list[0].get('sqmsCont', '') or ''
        num = ''.join(c for c in cont if c.isdigit() or c == '.')
        return to_float(num, None)
    return None


def extract_apsl_amt(item):
    """감정평가금액: apslEvlAmt 직접 필드 우선, 폴백으로 apslEvlClgList 평균"""
    direct = to_float(item.get('apslEvlAmt'), None)
    if direct:
        return direct
    raw = item.get('apslEvlClgList')
    if isinstance(raw, dict):
        raw = raw.get('apslEvlClg', [])
    if isinstance(raw, list) and raw:
        amts = [to_float(a.get('apslEvlAmt')) for a in raw if isinstance(a, dict)]
        amts = [a for a in amts if a > 0]
        return sum(amts) / len(amts) if amts else None
    return None


def compute_apsl_ratio(low_price, apsl, api_value=None):
    """감정가 대비 최저입찰가 비율(%). 직접 계산 우선, 불가하면 API 값, 그마저 없으면 None."""
    if low_price and apsl and apsl > 0:
        return round(low_price / apsl * 100, 2)
    return to_float(api_value, None)


def bid_window_state(bgng: str, end: str, now: datetime | None = None) -> str:
    """'open' | 'upcoming' | 'ended' | 'unknown'"""
    if not bgng or not end:
        return 'unknown'
    now_s = (now or datetime.now()).strftime('%Y%m%d%H%M')
    if str(end) < now_s:
        return 'ended'
    if str(bgng) > now_s:
        return 'upcoming'
    return 'open'


def normalize_item(item, rounds: list[dict] | None = None, now: datetime | None = None):
    """API 응답 아이템(현재 회차)을 통일된 형식으로 변환. rounds 는 전체 회차 일정."""
    area = extract_area(item)
    apsl = extract_apsl_amt(item)
    low_price = to_float(item.get('lowstBidPrcIndctCont'))
    api_ratio = item.get('apslPrcCtrsLowstBidRto')
    apsl_ratio = compute_apsl_ratio(low_price, apsl, api_ratio)
    fails = to_int(item.get('usbdNft'))

    stat_cd = item.get('pbctStatCd', '') or ''
    stat_nm_raw = item.get('pbctStatNm', '') or ''
    stat_nm = STATUS_NAME.get(stat_nm_raw, stat_nm_raw) if stat_nm_raw == stat_cd else stat_nm_raw
    if not stat_nm:
        stat_nm = STATUS_NAME.get(stat_cd, '')

    addr = (item.get('zadrNm') or item.get('cltrAdr') or item.get('cltrRadr') or
            ' '.join(filter(None, [item.get('lctnSdnm'), item.get('lctnSggnm'), item.get('lctnEmdNm')])))

    bgng = item.get('cltrBidBgngDt', '') or ''
    end = item.get('cltrBidEndDt', '') or ''
    days_left = None
    if len(end) >= 8:
        try:
            fmt, raw = ('%Y%m%d%H%M', end[:12]) if len(end) >= 12 else ('%Y%m%d', end[:8])
            days_left = (datetime.strptime(raw, fmt) - (now or datetime.now())).days
        except ValueError:
            pass

    round_list = sorted((round_summary(r) for r in (rounds or [item])),
                        key=lambda r: str(r.get('cltrBidBgngDt') or ''))

    return {
        'cltrMngNo':         item.get('cltrMngNo'),
        'pbctCdtnNo':        item.get('pbctCdtnNo'),
        'onbidCltrNm':       item.get('onbidCltrNm'),
        'cltrAdr':           addr,
        'lctnSdnm':          item.get('lctnSdnm', '') or '',
        'lctnSggnm':         item.get('lctnSggnm', '') or '',
        'lctnEmdNm':         item.get('lctnEmdNm', '') or '',
        'prptDivNm':         item.get('prptDivNm', '') or '',
        'cltrUsgSclsCtgrNm': item.get('cltrUsgSclsCtgrNm', '') or '',
        'cltrUsgMclsCtgrNm': item.get('cltrUsgMclsCtgrNm', '') or '',
        'area_sqm':          area,
        'apslEvlAmt':        apsl,
        'lowstBidPrc':       low_price,
        'apslRatio':         apsl_ratio,          # 직접 계산 (%)
        'apslRatio_api':     to_float(api_ratio, None),
        'discount_pct':      round(100 - apsl_ratio, 2) if apsl_ratio is not None else None,
        'usbdNft':           fails,
        'pbctStatCd':        stat_cd,
        'pbctStatNm':        stat_nm,
        'cltrBidBgngDt':     bgng,
        'cltrBidEndDt':      end,
        'pbctNsq':           item.get('pbctNsq', '') or '',
        'bid_window':        bid_window_state(bgng, end, now),
        'days_to_bid_end':   days_left,
        'round_count':       len(round_list),
        'rounds':            round_list,
    }


def normalize_grouped(raw_items: list[dict], now: datetime | None = None) -> list[dict]:
    """상세 API 원본(여러 회차 섞임) → 물건별 현재 회차 1건으로 정규화."""
    out = []
    for cn, rounds in group_rounds(raw_items).items():
        cur = select_current_round(rounds, now)
        out.append(normalize_item(cur, rounds=rounds, now=now))
    return out


# ─────────────────────────── 필터·점수 ───────────────────────────
def resolve_type_keyword(type_kw: str) -> str:
    if not type_kw:
        return ''
    for k, v in PROPERTY_TYPE_MAP.items():
        if k in type_kw or type_kw in k:
            return (v.get('cltrUsgSclsCtgrNm') or v.get('cltrUsgMclsCtgrNm')
                    or v.get('cltrUsgLclsCtgrNm') or type_kw)
    return type_kw


def score_item(item: dict) -> int:
    """우선순위 점수: 유찰×10(최대50) + 할인구간(30/20/10) + 마감 7일 이내 10"""
    score = min(to_int(item.get('usbdNft')), 5) * 10
    ratio = item.get('apslRatio')
    if ratio is not None:
        if ratio < 50:
            score += 30
        elif ratio < 70:
            score += 20
        elif ratio < 80:
            score += 10
    days = item.get('days_to_bid_end')
    if days is not None and 0 <= days <= 7:
        score += 10
    return score


def apply_filters(items, args, now: datetime | None = None):
    """클라이언트 사이드 필터 적용 (입력은 normalize 된 물건 목록)"""
    region_parts = (getattr(args, 'region', None) or '').strip().split()
    sido = region_parts[0] if region_parts else ''
    sggu = region_parts[1] if len(region_parts) > 1 else ''
    type_search_nm = resolve_type_keyword(getattr(args, 'type', None) or '')
    status = getattr(args, 'status', '모두') or '모두'

    filtered = []
    for item in items:
        if not isinstance(item, dict) or 'cltrMngNo' not in item:
            item = normalize_item(item, now=now)
        addr = item.get('cltrAdr', '') or ''
        lctnsido = item.get('lctnSdnm', '') or ''
        lctnsggu = item.get('lctnSggnm', '') or ''
        usage_nm = ' '.join([item.get('cltrUsgSclsCtgrNm', '') or '',
                             item.get('cltrUsgMclsCtgrNm', '') or '',
                             item.get('onbidCltrNm', '') or ''])
        low_price = to_float(item.get('lowstBidPrc'))
        fails = to_int(item.get('usbdNft'))
        area = item.get('area_sqm')

        if sido and (sido not in lctnsido if lctnsido else sido not in addr):
            continue
        if sggu and (sggu not in lctnsggu if lctnsggu else sggu not in addr):
            continue
        if type_search_nm and type_search_nm not in usage_nm:
            continue
        if args.price_min is not None and low_price < args.price_min:
            continue
        if args.price_max is not None and low_price > args.price_max:
            continue
        if area is not None:
            if args.area_min is not None and area < args.area_min:
                continue
            if args.area_max is not None and area > args.area_max:
                continue
        if args.min_fails is not None and fails < args.min_fails:
            continue
        if args.max_fails is not None and fails > args.max_fails:
            continue
        if status != '모두':
            target_cd = STATUS_CODE.get(status, '')
            if target_cd and item.get('pbctStatCd') != target_cd:
                continue

        item['priority_score'] = score_item(item)
        filtered.append(item)

    # 동일 물건 다회차 방어: 이미 normalize 단계에서 1건이지만, 외부 입력 대비 한 번 더
    best = {}
    for item in filtered:
        k = item.get('cltrMngNo')
        if not k:
            continue
        prev = best.get(k)
        if prev is None or _dt_key(item, 'cltrBidBgngDt') < _dt_key(prev, 'cltrBidBgngDt'):
            best[k] = item
    return sorted(best.values(), key=lambda x: x['priority_score'], reverse=True)


# ─────────────────────────── main ───────────────────────────
def build_parser():
    parser = argparse.ArgumentParser(description='온비드 공매 물건 필터 검색')
    parser.add_argument('--region',    help='지역 (예: "경기도", "경기도 수원시")')
    parser.add_argument('--type',      help='용도 (아파트/토지/상가/오피스텔/임야 등)')
    parser.add_argument('--area-min',  type=float, help='면적 하한 (㎡)')
    parser.add_argument('--area-max',  type=float, help='면적 상한 (㎡)')
    parser.add_argument('--price-min', type=float, help='최저입찰가 하한 (원)')
    parser.add_argument('--price-max', type=float, help='최저입찰가 상한 (원)')
    parser.add_argument('--min-fails', type=int,   help='유찰횟수 최소')
    parser.add_argument('--max-fails', type=int,   help='유찰횟수 최대')
    parser.add_argument('--status',    default='모두', help='입찰상태 (진행중/예정/모두)')
    parser.add_argument('--ids',       nargs='+',  help='물건관리번호 목록 (YYYY-NNNN-NNNNNN 형식)')
    parser.add_argument('--rows',      type=int, default=100, help='상세조회 numOfRows (회차 누락 방지, 기본 100)')
    parser.add_argument('--max-pbanc', type=int, default=100,
                        help='모드B: 처리할 최대 공고 수 (기본: 100, 많을수록 정확하나 느림)')
    parser.add_argument('--output',    default=OUTPUT, help='저장 경로')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    key = get_key('ONBID_API_KEY')
    now = datetime.now()

    print(f"\n{'=' * 60}\n온비드 공매 물건 검색\n{'=' * 60}")
    if args.region:    print(f"  지역:     {args.region}")
    if args.type:      print(f"  용도:     {args.type}")
    if args.area_min is not None or args.area_max is not None:
        print(f"  면적:     {args.area_min or ''}㎡ ~ {args.area_max or ''}㎡")
    if args.price_min is not None or args.price_max is not None:
        print(f"  가격:     {format_price(args.price_min)} ~ {format_price(args.price_max)}")
    if args.min_fails is not None or args.max_fails is not None:
        print(f"  유찰횟수: {args.min_fails or 0}회 ~ {args.max_fails if args.max_fails is not None else '∞'}회")
    print(f"  입찰상태: {args.status}\n")

    errors = []
    if args.ids:
        print(f"[모드 A] 상세 API 배치 조회 ({len(args.ids)}건)...")
        raw_detail, errors = call_detail_api(args.ids, rows=args.rows, key=key)
    else:
        print("[모드 B] 차세대 API 3단계 조회 (압류재산 전체 수집)")
        print("  ※ 유찰횟수·지역·용도·가격은 단계2에서 물건별 실제값(usbdNft 등)으로 사전필터\n")
        print("  [단계1] 공고목록 전체 수집 중...")
        pbanc_entries, err = call_list_api(key=key)
        if err:
            print(f"\n[!] 공고목록 조회 실패: {err}")
            print("  대안: --ids 옵션으로 물건관리번호를 직접 입력")
            print("  예시: python3 scripts/search_properties.py --ids 2026-0200-106923 ...")
            sys.exit(1)
        print(f"  → 고유 공고 {len(pbanc_entries)}건 (최신 공고일 순)")
        if len(pbanc_entries) > args.max_pbanc:
            pbanc_entries = pbanc_entries[:args.max_pbanc]
            print(f"  → max_pbanc={args.max_pbanc} 적용 → {len(pbanc_entries)}건")

        region_parts = (args.region or '').strip().split()
        pre_filter = {
            'sido':      region_parts[0] if region_parts else None,
            'sggu':      region_parts[1] if len(region_parts) > 1 else None,
            'type_kw':   resolve_type_keyword(args.type or '') or None,
            'min_fails': args.min_fails,
            'price_min': args.price_min,
            'price_max': args.price_max,
        }
        print(f"  [단계2] 물건관리번호 조회 ({len(pbanc_entries)}건 공고) + 사전필터...")
        cltr_nos, cltr_errs = call_pbanc_cltr_api(pbanc_entries, pre_filter=pre_filter, key=key, now=now)
        errors.extend(cltr_errs)
        print(f"  → 물건관리번호 {len(cltr_nos)}건 수집")
        if not cltr_nos:
            print("\n검색 범위 내 물건 없음")
            sys.exit(0)
        print(f"  [단계3] 상세 조회 ({len(cltr_nos)}건)...")
        raw_detail, det_errs = call_detail_api(cltr_nos, rows=args.rows, key=key)
        errors.extend(det_errs)
        print(f"  → 상세 {len(raw_detail)}건(회차 포함) 수신")

    raw_items = normalize_grouped(raw_detail, now=now)
    filtered = apply_filters(raw_items, args, now=now)

    print(f"\n{'─' * 60}\n검색 결과: 물건 {len(raw_items)}건 조회 → {len(filtered)}건 필터링\n{'─' * 60}")
    if filtered:
        print(f"{'순위':>3} {'물건명/주소':35} {'최저가':>8} {'감정가':>8} {'할인':>6} {'유찰':>4} {'면적':>7} {'회차':>4} {'상태':8}")
        print('─' * 96)
        for i, item in enumerate(filtered[:30], 1):
            display = (item.get('onbidCltrNm') or item.get('cltrAdr') or '')[:30]
            area = f"{item['area_sqm']:.0f}㎡" if item.get('area_sqm') else '-'
            disc = f"{item['discount_pct']:.0f}%" if item.get('discount_pct') is not None else '-'
            print(f"  {i:>2} {display:35} {format_price(item.get('lowstBidPrc')):>8} "
                  f"{format_price(item.get('apslEvlAmt')):>8} {disc:>6} {item.get('usbdNft', 0):>4}회 "
                  f"{area:>7} {item.get('pbctNsq', ''):>4} {(item.get('pbctStatNm') or '')[:8]}")
    else:
        print("  검색 결과 없음")
    if errors:
        print(f"\n오류 {len(errors)}건: {errors[:3]}")

    output = {
        'query_date':    now.strftime('%Y-%m-%d %H:%M'),
        'round_policy':  'earliest cltrBidBgngDt among rounds whose cltrBidEndDt >= query_date',
        'filters': {
            'region': args.region, 'type': args.type,
            'area_min': args.area_min, 'area_max': args.area_max,
            'price_min': args.price_min, 'price_max': args.price_max,
            'min_fails': args.min_fails, 'max_fails': args.max_fails,
            'status': args.status,
        },
        'total_fetched':  len(raw_items),
        'filtered_count': len(filtered),
        'properties':     filtered,
        'errors':         errors,
    }
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {args.output}\n{'=' * 60}\n")


if __name__ == '__main__':
    main()
