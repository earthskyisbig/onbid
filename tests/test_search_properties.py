"""search_properties.py — 회차 선택·비율 계산·필터·점수 (API 호출 없음)."""
import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

from search_properties import (apply_filters, compute_apsl_ratio, extract_apsl_amt,  # noqa: E402
                               extract_area, normalize_grouped, normalize_item,
                               resolve_type_keyword, score_item, select_current_round)

NOW = datetime(2026, 9, 2, 12, 0)


def _round(nsq, cdtn, bgng, end, price, **extra):
    return {'cltrMngNo': '2024-18146-006', 'pbctNsq': nsq, 'pbctCdtnNo': cdtn,
            'cltrBidBgngDt': bgng, 'cltrBidEndDt': end, 'lowstBidPrcIndctCont': price,
            'apslEvlAmt': 424_000_000, 'usbdNft': 10, 'pbctStatCd': '0001', 'pbctStatNm': '0001',
            'cltrUsgSclsCtgrNm': '다세대주택', 'lctnSdnm': '서울특별시', 'lctnSggnm': '은평구',
            'zadrNm': '서울특별시 은평구 대조동 93-3', 'bldSqms': '39.94', **extra}


ROUNDS = [
    _round('034', 1, '202609281400', '202609301700', 42_400_000),
    _round('035', 2, '202610061400', '202610071700', 38_160_000),
    _round('043', 3, '202611301400', '202612021700', 4_240_000),
]


def test_select_earliest_upcoming_round_not_max_pbctNsq():
    """2026-07-26 버그 재발 방지: pbctNsq 최댓값(043)이 아니라 가장 이른 회차(034)."""
    cur = select_current_round(list(reversed(ROUNDS)), NOW)
    assert cur['pbctNsq'] == '034'
    assert cur['lowstBidPrcIndctCont'] == 42_400_000


def test_select_skips_expired_rounds():
    expired = _round('033', 0, '202608011400', '202608031700', 46_640_000)
    cur = select_current_round([expired] + ROUNDS, NOW)
    assert cur['pbctNsq'] == '034'


def test_select_falls_back_to_all_when_every_round_expired():
    old = [_round('001', 1, '202501011400', '202501031700', 1), _round('002', 2, '202502011400', '202502031700', 2)]
    assert select_current_round(old, NOW)['pbctNsq'] == '001'


def test_compute_apsl_ratio_prefers_direct_calculation():
    assert compute_apsl_ratio(42_400_000, 424_000_000, api_value=None) == 10.0
    assert compute_apsl_ratio(42_400_000, 424_000_000, api_value='100') == 10.0   # API 값 무시
    assert compute_apsl_ratio(0, 424_000_000, api_value='55') == 55.0              # 폴백
    assert compute_apsl_ratio(None, None) is None


def test_normalize_item_fields_and_rounds():
    item = normalize_item(ROUNDS[0], rounds=ROUNDS, now=NOW)
    assert item['apslRatio'] == 10.0
    assert item['apslRatio_api'] is None
    assert item['discount_pct'] == 90.0
    assert item['pbctStatNm'] == '입찰준비중'       # 코드→이름 변환
    assert item['area_sqm'] == 39.94
    assert item['bid_window'] == 'upcoming'
    assert item['days_to_bid_end'] == 28
    assert item['round_count'] == 3
    assert [r['pbctNsq'] for r in item['rounds']] == ['034', '035', '043']


def test_normalize_grouped_one_item_per_property():
    other = _round('010', 9, '202609151400', '202609171700', 99, cltrMngNo='2026-0001-001')
    out = normalize_grouped(ROUNDS + [other], NOW)
    assert sorted(p['cltrMngNo'] for p in out) == ['2024-18146-006', '2026-0001-001']
    got = {p['cltrMngNo']: p['pbctNsq'] for p in out}
    assert got['2024-18146-006'] == '034'


def test_extract_area_priority():
    assert extract_area({'bldSqms': '84.9', 'landSqms': '300'}) == 84.9
    assert extract_area({'bldSqms': None, 'landSqms': '300'}) == 300.0
    assert extract_area({'sqmsList': [{'sqmsCont': '토지 123.4㎡'}]}) == 123.4
    assert extract_area({}) is None


def test_extract_apsl_amt_fallback_average():
    assert extract_apsl_amt({'apslEvlAmt': '1000'}) == 1000.0
    assert extract_apsl_amt({'apslEvlClgList': {'apslEvlClg': [{'apslEvlAmt': 100}, {'apslEvlAmt': 300}]}}) == 200.0
    assert extract_apsl_amt({}) is None


def test_score_item():
    assert score_item({'usbdNft': 10, 'apslRatio': 10.0, 'days_to_bid_end': 28}) == 80
    assert score_item({'usbdNft': 0, 'apslRatio': 100.0, 'days_to_bid_end': 3}) == 10
    assert score_item({'usbdNft': 2, 'apslRatio': 65.0, 'days_to_bid_end': None}) == 40
    assert score_item({'usbdNft': 1, 'apslRatio': None}) == 10


def test_resolve_type_keyword():
    assert resolve_type_keyword('아파트') == '아파트'
    assert resolve_type_keyword('다세대주택') == '다세대'
    assert resolve_type_keyword('') == ''
    assert resolve_type_keyword('창고시설') == '창고'
    assert resolve_type_keyword('기타') == '기타'


def _args(**kw):
    base = dict(region=None, type=None, area_min=None, area_max=None, price_min=None, price_max=None,
                min_fails=None, max_fails=None, status='모두')
    base.update(kw)
    return argparse.Namespace(**base)


def test_apply_filters_region_type_price_and_empty_type():
    items = normalize_grouped(ROUNDS, NOW)
    assert len(apply_filters(items, _args(region='서울특별시 은평구'), NOW)) == 1
    assert len(apply_filters(items, _args(region='경기도'), NOW)) == 0
    assert len(apply_filters(items, _args(type='다세대'), NOW)) == 1
    assert len(apply_filters(items, _args(type='아파트'), NOW)) == 0
    assert len(apply_filters(items, _args(type=''), NOW)) == 1           # 빈 문자열 = 필터 없음 (66ab3f7 회귀)
    assert len(apply_filters(items, _args(price_max=40_000_000), NOW)) == 0
    assert len(apply_filters(items, _args(price_min=0), NOW)) == 1        # 0 은 '없음'이 아니라 하한 0
    assert len(apply_filters(items, _args(min_fails=11), NOW)) == 0
    assert len(apply_filters(items, _args(status='진행중'), NOW)) == 0
    assert len(apply_filters(items, _args(status='예정'), NOW)) == 1


def test_apply_filters_dedups_multi_round_input_by_earliest_round():
    """normalize 전 원본 회차가 섞여 들어와도 가장 이른 회차 1건만 남는다."""
    raw = [normalize_item(r, now=NOW) for r in ROUNDS]
    out = apply_filters(raw, _args(), NOW)
    assert len(out) == 1 and out[0]['pbctNsq'] == '034'
    assert out[0]['priority_score'] == 80
