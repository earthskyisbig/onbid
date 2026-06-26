#!/usr/bin/env python3
"""
온비드 공매 물건 필터 검색 스크립트

사용법:
    python3 search_properties.py \
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
    --rows        페이지당 결과 수 (기본: 100)
"""
import argparse, json, os, sys, time
from datetime import datetime
from urllib.parse import unquote
from dotenv import load_dotenv
import requests

load_dotenv('/Users/leo-myung/onbid/.env')
KEY = unquote(os.getenv('ONBID_API_KEY', ''))
BASE = "https://apis.data.go.kr/B010003"
OUTPUT = '/Users/leo-myung/onbid/_workspace/01_search_results.json'

# 용도 키워드 → API 파라미터 매핑
PROPERTY_TYPE_MAP = {
    '아파트':     {'cltrUsgSclsCtgrNm': '아파트',   'cltrUsgSclsCtgrId': ''},
    '연립':       {'cltrUsgSclsCtgrNm': '연립',     'cltrUsgSclsCtgrId': ''},
    '다세대':     {'cltrUsgSclsCtgrNm': '다세대',   'cltrUsgSclsCtgrId': ''},
    '단독주택':   {'cltrUsgSclsCtgrNm': '단독',     'cltrUsgSclsCtgrId': ''},
    '오피스텔':   {'cltrUsgSclsCtgrNm': '오피스텔', 'cltrUsgSclsCtgrId': ''},
    '상가':       {'cltrUsgSclsCtgrNm': '상가',     'cltrUsgSclsCtgrId': ''},
    '상업용':     {'cltrUsgSclsCtgrNm': '상업',     'cltrUsgSclsCtgrId': ''},
    '토지':       {'cltrUsgMclsCtgrNm': '토지',     'cltrUsgSclsCtgrId': ''},
    '임야':       {'cltrUsgSclsCtgrNm': '임야',     'cltrUsgSclsCtgrId': ''},
    '공장':       {'cltrUsgSclsCtgrNm': '공장',     'cltrUsgSclsCtgrId': ''},
    '창고':       {'cltrUsgSclsCtgrNm': '창고',     'cltrUsgSclsCtgrId': ''},
    '건물':       {'cltrUsgLclsCtgrNm': '건물',     'cltrUsgSclsCtgrId': ''},
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


def call_list_api(min_fails=None):
    """
    OnbidPbancListSrvc2/getPbancList2 공고목록 API 호출 (차세대).
    prptDivCd=0007(압류재산)으로 전체 수집 후 고유 pbancMngNo를 반환.

    반복 패턴: 같은 pbancMngNo가 N회 나타나면 유찰 N-1회를 의미.
    min_fails가 지정되면 반복 횟수 >= min_fails+1인 pbancMngNo만 반환.
    """
    url = f"{BASE}/OnbidPbancListSrvc2/getPbancList2"
    all_items = []
    page = 1

    while True:
        p = {
            'serviceKey': KEY,
            'pageNo': page,
            'numOfRows': 100,
            'resultType': 'json',
            'prptDivCd': '0007',  # 압류재산 (현재 활성 공매 데이터)
            'pvctTrgtYn': 'N',
        }
        try:
            r = requests.get(url, params=p, timeout=15)
        except Exception as e:
            return None, f"네트워크 오류: {e}"

        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:200]}"

        try:
            data = r.json()
        except Exception:
            return None, f"JSON 파싱 실패: {r.text[:200]}"

        header = data.get('header', {})
        rc = header.get('resultCode', '00')
        if rc == '03':
            break
        if rc not in ('00', '', None):
            return None, f"API 오류 {rc}: {header.get('resultMsg')}"

        body = data.get('body', {})
        items_raw = body.get('items', {})
        items = items_raw.get('item', []) if isinstance(items_raw, dict) else (items_raw or [])
        if not isinstance(items, list):
            items = [items] if items else []
        if not items:
            break

        all_items.extend(items)

        total = int(body.get('totalCount', 0) or 0)
        if len(all_items) >= total or len(items) < 100:
            break
        page += 1
        time.sleep(0.15)

    # pbancMngNo별 반복 횟수 집계 → 유찰 횟수 추정
    from collections import Counter
    counter = Counter(i.get('pbancMngNo') for i in all_items if i.get('pbancMngNo'))

    # 유찰 필터: 반복 횟수 >= min_fails+1
    threshold = (min_fails + 1) if (min_fails is not None and min_fails > 0) else 1
    # 최신 공고가 마지막에 있으므로 역순으로 고유 pbancMngNo 추출
    seen = set()
    pbanc_nos = []
    for item in reversed(all_items):
        no = item.get('pbancMngNo')
        if not no or no in seen:
            continue
        if counter[no] >= threshold:
            seen.add(no)
            pbanc_nos.append({'pbancMngNo': no, 'usbdNft_est': counter[no] - 1})

    return pbanc_nos, None


def call_pbanc_cltr_api(pbanc_entries, pre_filter=None):
    """
    OnbidPbancCltrDtlSrvc2/getPbancCltrInf2 호출.
    공고관리번호(pbancMngNo) → 물건관리번호(cltrMngNo) 목록 변환.

    pre_filter: dict (선택). 단계2에서 사전 필터링하여 단계3 호출 수를 줄임.
      sido: str      지역 (예: '경기도') — cltrAdr에서 검색
      sggu: str      시군구 (예: '수원시')
      type_kw: str   용도 키워드 (예: '아파트')
      min_fails: int 최소 유찰 횟수
      price_min: float 최저입찰가 하한
      price_max: float 최저입찰가 상한
    """
    url = f"{BASE}/OnbidPbancCltrDtlSrvc2/getPbancCltrInf2"
    cltr_nos = []
    errors = []
    pf = pre_filter or {}

    for idx, entry in enumerate(pbanc_entries):
        no = entry.get('pbancMngNo') if isinstance(entry, dict) else entry
        time.sleep(1.0)
        if (idx + 1) % 20 == 0:
            print(f"    ...공고 {idx+1}/{len(pbanc_entries)} 처리 중 (통과 {len(cltr_nos)}건)")
        try:
            r = requests.get(url, params={
                'serviceKey': KEY,
                'pageNo': 1,
                'numOfRows': 50,
                'resultType': 'json',
                'pbancMngNo': no,
            }, timeout=15)
            if r.status_code == 429:
                wait = int(r.headers.get('Retry-After', 30))
                print(f"\n    [!] Rate limit(429) — {wait}초 대기 후 재시도...")
                time.sleep(wait)
                r = requests.get(url, params={
                    'serviceKey': KEY, 'pageNo': 1, 'numOfRows': 50,
                    'resultType': 'json', 'pbancMngNo': no,
                }, timeout=15)
            if not r.text.strip():
                continue
            data = r.json()
        except Exception as e:
            errors.append({'pbancMngNo': no, 'error': str(e)})
            continue

        header = data.get('header') or data.get('result') or {}
        rc = header.get('resultCode', '00')
        if rc == '03' or 'DB_ERROR' in header.get('resultMsg', ''):
            continue
        if rc not in ('00', '', None):
            errors.append({'pbancMngNo': no, 'error': header.get('resultMsg', f'rc={rc}')})
            continue

        items_raw = data.get('body', {}).get('items', {})
        items = items_raw.get('item', []) if isinstance(items_raw, dict) else (items_raw or [])
        if not isinstance(items, list):
            items = [items] if items else []

        # cltrMngNo별 최신 회차(pbctNsq 최대)만 선별
        best = {}
        for item in items:
            cn = item.get('cltrMngNo')
            if not cn:
                continue
            prev = best.get(cn)
            if prev is None or str(item.get('pbctNsq', '')) >= str(prev.get('pbctNsq', '')):
                best[cn] = item

        # 사전 필터 적용
        for cn, item in best.items():
            if cn in cltr_nos:
                continue

            addr = item.get('cltrAdr', '') or ''
            usage = ' '.join(filter(None, [
                item.get('cltrUsgSclsCtgrNm', ''),
                item.get('cltrUsgMclsCtgrNm', ''),
                item.get('cltrUsgLclsCtgrNm', ''),
                item.get('onbidCltrNm', ''),
            ]))
            fails = int(item.get('usbdNft', 0) or 0)
            try:
                price = float(item.get('lowstBidPrcIndctCont', 0) or 0)
            except (ValueError, TypeError):
                price = 0.0

            if pf.get('sido') and pf['sido'] not in addr:
                continue
            if pf.get('sggu') and pf['sggu'] not in addr:
                continue
            if pf.get('type_kw') and pf['type_kw'] not in usage:
                continue
            if pf.get('min_fails') is not None and fails < pf['min_fails']:
                continue
            if pf.get('price_min') and price < pf['price_min']:
                continue
            if pf.get('price_max') and price > pf['price_max']:
                continue

            cltr_nos.append(cn)

    return cltr_nos, errors


def call_detail_api(cltr_mng_nos):
    """
    OnbidRlstDtlSrvc2/getRlstDtlInf2 상세 API 배치 호출.
    cltrMngNo 목록을 받아 각각 조회 후 합산.
    """
    url = f"{BASE}/OnbidRlstDtlSrvc2/getRlstDtlInf2"
    results = []
    errors = []

    for no in cltr_mng_nos:
        time.sleep(1.0)
        data = None
        for attempt in range(3):
            try:
                r = requests.get(url, params={
                    'serviceKey': KEY,
                    'pageNo': 1,
                    'numOfRows': 10,
                    'resultType': 'json',
                    'cltrMngNo': no,
                }, timeout=20)
                if r.status_code == 429:
                    wait = int(r.headers.get('Retry-After', 30))
                    print(f"\n    [!] Rate limit(429) — {wait}초 대기 후 재시도...")
                    time.sleep(wait)
                    continue
                if not r.text.strip():
                    raise ValueError("빈 응답")
                data = r.json()
                break
            except (requests.exceptions.ReadTimeout, ValueError):
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
                else:
                    errors.append({'cltrMngNo': no, 'error': '빈 응답/타임아웃'})
            except Exception as e:
                errors.append({'cltrMngNo': no, 'error': str(e)})
                break
        if data is None:
            continue

        # 응답 구조: header/body (정상) 또는 result (차세대 오류 형식)
        header = data.get('header') or data.get('result') or {}
        rc = header.get('resultCode', '00')
        msg = header.get('resultMsg', '')
        if rc == '03' or 'DB_ERROR' in msg:
            continue  # NODATA 또는 서버 일시 오류 — 정상 skip
        if rc not in ('00', '', None):
            errors.append({'cltrMngNo': no, 'error': msg or f'rc={rc}'})
            continue

        items_raw = data.get('body', {}).get('items', {}).get('item', [])
        items = items_raw if isinstance(items_raw, list) else ([items_raw] if items_raw else [])
        results.extend(items)

    return results, errors


def extract_area(item):
    """물건 면적 추출
    우선순위: bldSqms(건물면적) > landSqms(토지면적) > sqmsList 첫 항목
    (cltrPrclList는 null인 경우가 많아 사용하지 않음 — 2026-06-24 확인)
    """
    bld = item.get('bldSqms')
    if bld:
        try:
            return float(bld)
        except (ValueError, TypeError):
            pass
    land = item.get('landSqms')
    if land:
        try:
            return float(land)
        except (ValueError, TypeError):
            pass
    sqms_list = item.get('sqmsList')
    if isinstance(sqms_list, list) and sqms_list:
        cont = sqms_list[0].get('sqmsCont', '')
        num = ''.join(c for c in cont if c.isdigit() or c == '.')
        try:
            return float(num)
        except (ValueError, TypeError):
            pass
    return None


def extract_apsl_amt(item):
    """감정평가금액 추출
    apslEvlAmt 직접 필드 우선 (2026-06-24: 최고 평균값으로 확인)
    """
    direct = item.get('apslEvlAmt')
    if direct:
        try:
            return float(direct)
        except (ValueError, TypeError):
            pass
    # 폴백: apslEvlClgList 리스트 평균
    raw = item.get('apslEvlClgList')
    if not raw:
        return None
    if isinstance(raw, dict):
        raw = raw.get('apslEvlClg', [])
    if isinstance(raw, list) and raw:
        amts = [float(a.get('apslEvlAmt', 0) or 0) for a in raw if isinstance(a, dict)]
        amts = [a for a in amts if a > 0]
        return sum(amts) / len(amts) if amts else None
    return None


def normalize_item(item):
    """API 응답 아이템을 통일된 형식으로 변환"""
    area = extract_area(item)
    apsl = extract_apsl_amt(item)
    low_price = float(item.get('lowstBidPrcIndctCont', 0) or 0)
    apsl_ratio = float(item.get('apslPrcCtrsLowstBidRto', 100) or 100)
    fails = int(item.get('usbdNft', 0) or 0)

    stat_cd = item.get('pbctStatCd', '')
    # pbctStatNm API 버그: 코드값을 반환하는 경우 이름으로 변환
    stat_nm_raw = item.get('pbctStatNm', '')
    stat_nm = STATUS_NAME.get(stat_nm_raw, stat_nm_raw) if stat_nm_raw == stat_cd else stat_nm_raw

    # 주소: cltrAdr(null 빈번) → zadrNm → cltrRadr → 시도+시군구+읍면동 조합
    addr = (item.get('zadrNm') or item.get('cltrAdr') or item.get('cltrRadr') or
            ' '.join(filter(None, [item.get('lctnSdnm'), item.get('lctnSggnm'), item.get('lctnEmdNm')])))

    return {
        'cltrMngNo':         item.get('cltrMngNo'),
        'pbctCdtnNo':        item.get('pbctCdtnNo'),
        'onbidCltrNm':       item.get('onbidCltrNm'),
        'cltrAdr':           addr,
        'lctnSdnm':          item.get('lctnSdnm', ''),
        'lctnSggnm':         item.get('lctnSggnm', ''),
        'prptDivNm':         item.get('prptDivNm', ''),
        'cltrUsgSclsCtgrNm': item.get('cltrUsgSclsCtgrNm', ''),
        'cltrUsgMclsCtgrNm': item.get('cltrUsgMclsCtgrNm', ''),
        'area_sqm':          area,
        'apslEvlAmt':        apsl,
        'lowstBidPrc':       low_price,
        'apslRatio':         apsl_ratio,
        'usbdNft':           fails,
        'pbctStatCd':        stat_cd,
        'pbctStatNm':        stat_nm,
        'cltrBidBgngDt':     item.get('cltrBidBgngDt', ''),
        'cltrBidEndDt':      item.get('cltrBidEndDt', ''),
        'pbctNsq':           item.get('pbctNsq', ''),
    }


def apply_filters(items, args):
    """클라이언트 사이드 필터 적용"""
    filtered = []

    # 지역 파싱
    region_parts = (args.region or '').strip().split() if args.region else []
    sido = region_parts[0] if region_parts else ''
    sggu = region_parts[1] if len(region_parts) > 1 else ''

    # 용도 키워드
    type_kw = args.type or ''
    # 공식 매핑에서 검색 키워드 가져오기
    type_search_nm = ''
    for k, v in PROPERTY_TYPE_MAP.items():
        if k in type_kw or type_kw in k:
            type_search_nm = v.get('cltrUsgSclsCtgrNm') or v.get('cltrUsgMclsCtgrNm') or type_kw
            break
    if not type_search_nm:
        type_search_nm = type_kw  # 직접 키워드 사용

    for raw in items:
        item = normalize_item(raw) if 'cltrMngNo' not in raw else raw
        if not isinstance(raw, dict) or 'cltrMngNo' not in raw:
            item = normalize_item(raw)
        else:
            item = {**raw}

        addr = item.get('cltrAdr', '')
        lctnsido = item.get('lctnSdnm', '')
        lctnsggu = item.get('lctnSggnm', '')
        usage_nm = (item.get('cltrUsgSclsCtgrNm', '') + ' ' +
                    item.get('cltrUsgMclsCtgrNm', '') + ' ' +
                    item.get('onbidCltrNm', ''))
        low_price = float(item.get('lowstBidPrc', 0) or 0)
        fails = int(item.get('usbdNft', 0) or 0)
        area = item.get('area_sqm')

        # 지역 필터: lctnSdnm/lctnSggnm 우선, 없으면 addr 폴백
        if sido:
            if lctnsido and sido not in lctnsido:
                continue
            elif not lctnsido and sido not in addr:
                continue
        if sggu:
            if lctnsggu and sggu not in lctnsggu:
                continue
            elif not lctnsggu and sggu not in addr:
                continue

        # 용도 필터
        if type_search_nm and type_search_nm not in usage_nm:
            continue

        # 가격 필터
        if args.price_min and low_price < args.price_min:
            continue
        if args.price_max and low_price > args.price_max:
            continue

        # 면적 필터
        if area is not None:
            if args.area_min and area < args.area_min:
                continue
            if args.area_max and area > args.area_max:
                continue

        # 유찰횟수 필터
        if args.min_fails is not None and fails < args.min_fails:
            continue
        if args.max_fails is not None and fails > args.max_fails:
            continue

        # 입찰상태 필터 (기본: 진행중+준비중)
        if args.status and args.status != '모두':
            target_cd = STATUS_CODE.get(args.status, '')
            if target_cd and item.get('pbctStatCd') != target_cd:
                continue

        # 우선순위 점수 산정
        score = 0
        score += min(fails, 5) * 10
        ratio = float(item.get('apslRatio', 100) or 100)
        if ratio < 50:
            score += 30
        elif ratio < 70:
            score += 20
        elif ratio < 80:
            score += 10

        # 입찰 임박 (7일 이내)
        bid_end = item.get('cltrBidEndDt', '')
        if bid_end and len(bid_end) >= 8:
            try:
                end_dt = datetime.strptime(bid_end[:8], '%Y%m%d')
                days_left = (end_dt - datetime.now()).days
                if 0 <= days_left <= 7:
                    score += 10
            except ValueError:
                pass

        item['priority_score'] = score
        filtered.append(item)

    # 동일 물건(cltrMngNo)의 여러 회차 중 최신 회차(pbctNsq 최대)만 남김
    best = {}
    for item in filtered:
        key = item.get('cltrMngNo', '')
        if not key:
            continue
        prev = best.get(key)
        if prev is None or str(item.get('pbctNsq', '')) > str(prev.get('pbctNsq', '')):
            best[key] = item
    filtered = list(best.values())

    return sorted(filtered, key=lambda x: x['priority_score'], reverse=True)


def format_price(v):
    if not v:
        return '-'
    v = float(v)
    if v >= 1e8:
        return f"{v/1e8:.1f}억"
    return f"{int(v/10000):,}만"


def main():
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
    parser.add_argument('--rows',      type=int, default=100, help='페이지당 결과 수')
    parser.add_argument('--max-pbanc', type=int, default=100,
                        help='모드B: 처리할 최대 공고 수 (기본: 100, 많을수록 정확하나 느림)')
    parser.add_argument('--output',    default=OUTPUT, help='저장 경로')
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"온비드 공매 물건 검색")
    print(f"{'='*60}")
    if args.region:    print(f"  지역:     {args.region}")
    if args.type:      print(f"  용도:     {args.type}")
    if args.area_min or args.area_max:
        print(f"  면적:     {args.area_min or ''}㎡ ~ {args.area_max or ''}㎡")
    if args.price_min or args.price_max:
        mn = format_price(args.price_min) if args.price_min else ''
        mx = format_price(args.price_max) if args.price_max else ''
        print(f"  가격:     {mn} ~ {mx}")
    if args.min_fails is not None or args.max_fails is not None:
        print(f"  유찰횟수: {args.min_fails or 0}회 ~ {args.max_fails or '∞'}회")
    print(f"  입찰상태: {args.status}")
    print()

    raw_items = []
    errors = []

    if args.ids:
        # 모드 A: 물건관리번호 직접 제공 → 상세 API 배치 조회
        print(f"[모드 A] 상세 API 배치 조회 ({len(args.ids)}건)...")
        raw_items, errors = call_detail_api(args.ids)
        raw_items = [normalize_item(i) for i in raw_items]
    else:
        # 모드 B: 차세대 API 3단계 (공고목록 전체 → 유찰 필터 → 물건관리번호 → 상세)
        # prptDivCd=0007(압류재산) 전체 수집, pbancMngNo 반복 횟수로 유찰 횟수 추정
        print("[모드 B] 차세대 API 3단계 조회 (압류재산 전체 수집)")
        print("  ※ 유찰횟수는 공고 반복 횟수로 추정, 나머지 필터는 상세 조회 후 클라이언트 적용")
        print()

        # 단계 1: 공고목록 전체 수집 + 유찰 횟수 사전 필터
        min_fails_hint = args.min_fails  # 유찰 필터를 단계1에서 사전 적용
        print(f"  [단계1] 공고목록 전체 수집 중...")
        pbanc_entries, err = call_list_api(min_fails=min_fails_hint)
        if err:
            print(f"\n[!] 공고목록 조회 실패: {err}")
            print("  대안: --ids 옵션으로 물건관리번호를 직접 입력")
            print("  예시: python3 search_properties.py --ids 2026-0200-106923 ...")
            sys.exit(1)
        print(f"  → 유효 공고 {len(pbanc_entries)}건 (유찰 {min_fails_hint or 0}회+ 필터 적용)")

        # max_pbanc 제한
        if len(pbanc_entries) > args.max_pbanc:
            pbanc_entries = pbanc_entries[:args.max_pbanc]
            print(f"  → max_pbanc={args.max_pbanc} 적용 → {len(pbanc_entries)}건")

        # 단계 2: 공고별 물건관리번호 + 사전 필터
        # (용도/지역/유찰/가격은 단계2에서 미리 적용 → 단계3 호출 수 최소화)
        region_parts = (args.region or '').strip().split()
        pre_filter = {
            'sido':      region_parts[0] if region_parts else None,
            'sggu':      region_parts[1] if len(region_parts) > 1 else None,
            'type_kw':   args.type or None,
            'min_fails': args.min_fails,
            'price_min': args.price_min,
            'price_max': args.price_max,
        }
        print(f"  [단계2] 물건관리번호 조회 ({len(pbanc_entries)}건 공고) + 사전필터...")
        cltr_nos, cltr_errs = call_pbanc_cltr_api(pbanc_entries, pre_filter=pre_filter)
        errors.extend(cltr_errs)
        print(f"  → 물건관리번호 {len(cltr_nos)}건 수집")

        if not cltr_nos:
            print("\n검색 범위 내 물건 없음")
            sys.exit(0)

        # 단계 3: 상세 조회 (OnbidRlstDtlSrvc2/getRlstDtlInf2)
        print(f"  [단계3] 상세 조회 ({len(cltr_nos)}건)...")
        raw_detail, det_errs = call_detail_api(cltr_nos)
        errors.extend(det_errs)
        print(f"  → 상세 {len(raw_detail)}건 수신")
        raw_items = [normalize_item(i) for i in raw_detail]

    # 클라이언트 사이드 필터 적용
    filtered = apply_filters(raw_items, args)

    # 결과 출력
    print(f"\n{'─'*60}")
    print(f"검색 결과: {len(raw_items)}건 조회 → {len(filtered)}건 필터링")
    print(f"{'─'*60}")

    if filtered:
        print(f"{'순위':>3} {'물건명/주소':35} {'최저가':>8} {'감정가':>8} {'유찰':>4} {'면적':>7} {'상태':8}")
        print('─' * 80)
        for i, item in enumerate(filtered[:30], 1):
            nm = (item.get('onbidCltrNm', '') or '')[:30]
            addr = (item.get('cltrAdr', '') or '')
            display = nm if nm else addr[:30]
            low = format_price(item.get('lowstBidPrc'))
            apsl = format_price(item.get('apslEvlAmt'))
            fails = item.get('usbdNft', 0)
            area = f"{item.get('area_sqm'):.0f}㎡" if item.get('area_sqm') else '-'
            stat = item.get('pbctStatNm', '')[:8]
            print(f"  {i:>2} {display:35} {low:>8} {apsl:>8} {fails:>4}회 {area:>7} {stat}")
    else:
        print("  검색 결과 없음")

    if errors:
        print(f"\n오류 {len(errors)}건: {errors[:3]}")

    # JSON 저장
    output = {
        'query_date':    datetime.now().strftime('%Y-%m-%d %H:%M'),
        'filters': {
            'region':    args.region,
            'type':      args.type,
            'area_min':  args.area_min,
            'area_max':  args.area_max,
            'price_min': args.price_min,
            'price_max': args.price_max,
            'min_fails': args.min_fails,
            'max_fails': args.max_fails,
            'status':    args.status,
        },
        'total_fetched':  len(raw_items),
        'filtered_count': len(filtered),
        'properties':     filtered,
        'errors':         errors,
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n저장: {args.output}")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
