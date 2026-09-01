"""2026-09-02 후속 개선: 취득세율 자동 산정, 비아파트 실거래 종류, 공고목록 압축, PDF 파서."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

from roi_calculator import ROIInputError, acquisition_tax_rate, calc_auction, main as roi_main  # noqa: E402
from fetch_market_data import KINDS, match, parse_xml, summarize, _record_trade, resolve_lawd  # noqa: E402
from search_properties import summarize_pbanc_list  # noqa: E402
from analyze_documents import (analyze, classify_doc, parse_appraisal, parse_land_use,  # noqa: E402
                               parse_property_statement, risk_flags)


# ─────────────────────────── 취득세율 ───────────────────────────
@pytest.mark.parametrize('price,area,houses,adj,expected', [
    (300_000_000, 59, 1, False, 0.011),     # 1주택 6억 이하 85㎡ 이하
    (300_000_000, 100, 1, False, 0.013),    # + 농특세 0.2%
    (750_000_000, 84, 1, False, 0.022),     # 6~9억 누진: (7.5×2/3 − 3)=2.00% + 0.2%
    (600_000_000, 84, 1, False, 0.011),     # 경계값 6억 → 1%
    (900_000_000, 84, 1, False, 0.033),     # 경계값 9억 → 3%
    (1_200_000_000, 84, 1, False, 0.033),   # 9억 초과 3% + 0.3%
    (300_000_000, 59, 2, False, 0.011),     # 비조정 2주택 = 일반세율
    (300_000_000, 59, 2, True, 0.084),      # 조정 2주택 8% + 0.4%
    (300_000_000, 100, 2, True, 0.090),     # + 농특세 0.6%
    (300_000_000, 59, 3, False, 0.084),     # 비조정 3주택 8%
    (300_000_000, 59, 3, True, 0.124),      # 조정 3주택 12% + 0.4%
    (300_000_000, 100, 4, False, 0.134),    # 비조정 4주택 12% + 0.4% + 1.0%
])
def test_house_acquisition_tax(price, area, houses, adj, expected):
    r = acquisition_tax_rate('house', price, area, houses, adj)
    assert abs(r['rate'] - expected) < 1e-6, r['basis']


def test_nonhouse_acquisition_tax():
    assert acquisition_tax_rate('land')['rate'] == 0.046
    assert acquisition_tax_rate('commercial')['rate'] == 0.046
    assert acquisition_tax_rate('officetel')['rate'] == 0.046
    assert acquisition_tax_rate('farmland')['rate'] == 0.034
    with pytest.raises(ROIInputError):
        acquisition_tax_rate('house')            # 가액 없음
    with pytest.raises(ROIInputError):
        acquisition_tax_rate('spaceship', 1)


def test_calc_auction_auto_tax_by_kind():
    r = calc_auction({'appraisalValue': 3e8, 'bidPrice': 2.5e8, 'expectedSalePrice': 3.2e8,
                      'holdingPeriodMonths': 24, 'propertyKind': 'house', 'areaSqm': 59,
                      'assumedRightsAmount': 0, 'transferTax': 0})
    assert r['inputs']['acquisitionTaxRate'] == 0.011
    assert r['acquisitionTaxBasis']['basis'].startswith('주택 6억 이하')
    assert r['costs']['acquisitionTax'] == 2_750_000
    # 명시 세율이 있으면 kind 무시
    r2 = calc_auction({'appraisalValue': 3e8, 'bidPrice': 2.5e8, 'expectedSalePrice': 3.2e8,
                       'holdingPeriodMonths': 24, 'propertyKind': 'house', 'acquisitionTaxRate': 0.046})
    assert r2['inputs']['acquisitionTaxRate'] == 0.046 and r2['acquisitionTaxBasis'] is None


def test_scenarios_tax_varies_with_bid(capsys):
    # 6억 경계를 넘나드는 최저가: 보수(6.0억 → 1%)와 공격(6.72억 → 누진) 세율이 달라야 한다
    rc = roi_main(['scenarios', '--appraisal', '700000000', '--min-bid', '600000000', '--fair-value', '800000000',
                   '--kind', 'house', '--area-sqm', '84', '--assumed-rights', '0', '--transfer-tax', '0', '--format', 'json'])
    assert rc == 0
    import json
    d = json.loads(capsys.readouterr().out)
    assert d['scenarios']['conservative']['inputs']['acquisitionTaxRate'] == 0.011
    assert d['scenarios']['aggressive']['inputs']['acquisitionTaxRate'] > 0.011


def test_tax_cli():
    assert roi_main(['tax', '--kind', 'land']) == 0
    assert roi_main(['tax', '--kind', 'house']) == 2   # price 없음


# ─────────────────────────── 비아파트 실거래 ───────────────────────────
def test_kinds_config_complete():
    for k, cfg in KINDS.items():
        assert cfg['trade'] and cfg['name'] and cfg['area'] and cfg['match'], k
    assert KINDS['land']['rent'] is None and KINDS['shop']['rent'] is None


LAND_XML = """<response><header><resultCode>000</resultCode></header><body><items>
<item><umdNm>검천리</umdNm><jimok>임야</jimok><landUse>자연녹지지역</landUse><dealArea>620</dealArea>
<dealAmount>18,600</dealAmount><dealYear>2026</dealYear><dealMonth>5</dealMonth><dealDay>2</dealDay><dealingGbn>중개거래</dealingGbn></item>
<item><umdNm>귀여리</umdNm><jimok>전</jimok><landUse>계획관리지역</landUse><dealArea>300</dealArea>
<dealAmount>9,000</dealAmount><dealYear>2026</dealYear><dealMonth>4</dealMonth><dealDay>1</dealDay></item>
</items></body></response>"""


def test_land_match_record_and_per_sqm_summary():
    items, err = parse_xml(LAND_XML)
    assert err is None and len(items) == 2
    assert match(items[0], '검천리', 500, 400, 'land') is True
    assert match(items[1], '검천리', 500, 400, 'land') is False       # 읍면동 불일치
    assert match(items[0], '임야', 0, 0, 'land') is True              # 지목으로도 매칭
    rec = _record_trade(items[0], 'land')
    assert rec['dealAmount'] == 186_000_000 and rec['area'] == 620.0
    assert rec['price_per_sqm'] == 300_000 and rec['jimok'] == '임야'
    s = summarize([rec], [], apsl_amt=120_000_000, target_area=500)
    assert s['price_per_sqm_median'] == 300_000
    assert s['implied_value_at_target_area'] == 150_000_000
    assert s['vs_apsl'] == 30_000_000                                 # 환산가 기준 비교
    assert s['liquidity_flag'].startswith('거래 3건 미만')


def test_apt_record_keeps_aptNm_compat():
    xml = """<r><header><resultCode>000</resultCode></header><body><items><item><aptNm>은마</aptNm><excluUseAr>76.79</excluUseAr>
    <dealAmount>335,000</dealAmount><dealYear>2026</dealYear><dealMonth>8</dealMonth><dealDay>3</dealDay></item></items></body></r>"""
    items, _ = parse_xml(xml)
    rec = _record_trade(items[0], 'apt')
    assert rec['aptNm'] == '은마' and rec['name'] == '은마' and 'price_per_sqm' not in rec


def test_resolve_lawd():
    assert resolve_lawd('서울 은평구') == '11380'
    assert resolve_lawd('41610') == '41610'
    assert resolve_lawd('화성시청') is None


# ─────────────────────────── 공고목록 압축 (유찰 추정 폐기) ───────────────────────────
def test_summarize_pbanc_list_does_not_filter_and_orders_latest_first():
    rows = [
        {'pbancMngNo': 'A', 'pbctNsq': '013', 'pbancYmd': '20251201', 'pbancKindNm': '일반공고'},
        {'pbancMngNo': 'A', 'pbctNsq': '014', 'pbancYmd': '20251201', 'pbancKindNm': '일반공고'},
        {'pbancMngNo': 'B', 'pbctNsq': '1', 'pbancYmd': '20260801', 'pbancKindNm': '취소공고'},
        {'pbancMngNo': None},
    ]
    out = summarize_pbanc_list(rows)
    assert [e['pbancMngNo'] for e in out] == ['B', 'A']
    a = next(e for e in out if e['pbancMngNo'] == 'A')
    assert a['list_count'] == 2 and a['pbctNsq_max'] == 14
    assert all('usbdNft_est' not in e for e in out)   # 반복횟수 기반 유찰 추정 필드는 더 이상 없음


# ─────────────────────────── PDF 파서 ───────────────────────────
SAMPLE_TEXT = """감정평가서
감정평가액 : 250,000,000원 (금 이억오천만원정)
기준시점 2026년 03월 15일 / 감정평가방법: 거래사례비교법
전용면적 25.41㎡, 대지권 5.12㎡. 사용승인일 2021.01.20 철근콘크리트조
공시지가 4,500,000원/㎡
재산명세서
임차인 현황: 임차보증금 30,000,000원, 월차임 850,000원. 전입세대 확인됨.
등기사항: 1순위 근저당권 채권최고액 180,000,000원
유치권 신고 없음. 법정지상권 해당 없음. 체납관리비 확인 필요. 가처분 등기 있음.
토지이용계획: 제2종일반주거지역, 건폐율 60%, 용적률 200%. 지구단위계획구역."""


def test_parse_appraisal_from_text():
    a = parse_appraisal(SAMPLE_TEXT)
    assert a['amount'] == 250_000_000
    assert a['base_date'] == '2026-03-15'
    assert a['method'] == '거래사례비교법'
    assert 25.41 in a['areas_sqm'] and 5.12 in a['areas_sqm']
    assert a['gongsi_price'] == 4_500_000
    assert a['build_year'] == 2021
    assert a['structure'] == '철근콘크리트조'


def test_parse_statement_and_land_use():
    s = parse_property_statement(SAMPLE_TEXT)
    assert s['tenant_mentioned'] and s['tenants'][0]['deposit'] == 30_000_000
    assert s['monthly_rents'][0]['monthly'] == 850_000
    assert s['senior_claims_sum'] == 180_000_000
    lu = parse_land_use(SAMPLE_TEXT)
    assert lu['zone'] == '제2종일반주거지역' and lu['bcr'] == 60 and lu['far'] == 200
    assert '지구단위계획' in lu['restrictions']


def test_risk_flags_negation():
    flags = {f['keyword']: f for f in risk_flags(SAMPLE_TEXT)}
    assert flags['유치권']['negated'] is True
    assert flags['법정지상권']['negated'] is True
    assert flags['가처분']['negated'] is False
    assert flags['체납관리비']['negated'] is False


def test_classify_doc():
    assert classify_doc('감정평가서.pdf', '') == 'appraisal'
    assert classify_doc('x.pdf', '재산명세서 ...') == 'property_statement'
    assert classify_doc('토지이용계획확인서.pdf', '') == 'land_use'
    assert classify_doc('x.pdf', '') == 'unknown'


def test_analyze_real_pdf_fixture():
    fixture = ROOT / 'tests' / 'fixtures' / 'sample_appraisal.pdf'
    if not fixture.exists():
        pytest.skip('fixture PDF 없음')
    pytest.importorskip('pdfplumber')
    res = analyze('TEST', [fixture])
    assert res['documents'][0]['error'] is None
    assert res['appraisal']['amount'] == 250_000_000
    assert res['property_statement']['senior_claims_sum'] == 180_000_000
    assert any(f['keyword'] == '유치권' and f['negated'] for f in res['risk_flags'])
    assert res['rights_analysis']['assumed_amount'] is None   # LLM 이 채울 자리
