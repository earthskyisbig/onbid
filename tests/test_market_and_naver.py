"""fetch_market_data.py / fetch_naver_listings.py 파서·집계 (네트워크 없음)."""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

from fetch_market_data import (LAWD_CD, _amount_won, parse_xml, recent_months,  # noqa: E402
                               summarize)
from fetch_naver_listings import calculate_gap, parse_naver_price  # noqa: E402
from common import format_price, parse_onbid_response  # noqa: E402

XML_OK = """<response><header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header>
<body><items>
<item><aptNm>은마</aptNm><excluUseAr>76.79</excluUseAr><dealAmount>335,000</dealAmount>
<dealYear>2026</dealYear><dealMonth>8</dealMonth><dealDay>3</dealDay><floor>5</floor><buildYear>1979</buildYear></item>
<item><aptNm>은마</aptNm><excluUseAr>84.43</excluUseAr><dealAmount>340,000</dealAmount>
<dealYear>2026</dealYear><dealMonth>7</dealMonth><dealDay>1</dealDay><floor>9</floor><buildYear>1979</buildYear><cdealType>O</cdealType></item>
</items></body></response>"""

XML_ERR = """<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>30</returnReasonCode>
<resultCode>30</resultCode><resultMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</resultMsg></cmmMsgHeader></OpenAPI_ServiceResponse>"""


def test_parse_xml_ok_and_error():
    items, err = parse_xml(XML_OK)
    assert err is None and len(items) == 2
    items, err = parse_xml(XML_ERR)
    assert items == [] and '30' in err
    assert parse_xml('')[1] == '빈 응답'
    assert 'XML 파싱' in parse_xml('<broken')[1]


def test_amount_won():
    assert _amount_won('335,000') == 3_350_000_000
    assert _amount_won(' 6,000 ') == 60_000_000
    assert _amount_won('') is None


def test_recent_months_crosses_year():
    ms = recent_months(3, base=datetime(2026, 1, 15))
    assert ms == ['202601', '202512', '202511']


def test_summarize_with_apsl_and_flags():
    trade = [{'dealAmount': 300_000_000, 'dealYMD': '2026-08-01', 'buildYear': '2020'},
             {'dealAmount': 320_000_000, 'dealYMD': '2026-07-01', 'buildYear': '2020'},
             {'dealAmount': 340_000_000, 'dealYMD': '2026-06-01', 'buildYear': '2020'}]
    rent = [{'type': '전세', 'deposit': 200_000_000}, {'type': '월세', 'deposit': 30_000_000}]
    s = summarize(trade, rent, apsl_amt=300_000_000, low_bid=250_000_000)
    assert s['trade_count'] == 3 and s['trade_avg'] == 320_000_000 and s['trade_median'] == 320_000_000
    assert s['trade_latest'] == '2026-08-01'
    assert s['jeonse_ratio_pct'] == 62.5
    assert s['vs_apsl_pct'] == 6.7 and s['vs_lowbid_pct'] == 28.0
    assert s['liquidity_flag'] == 'OK'
    assert summarize([], [], 1)['liquidity_flag'].startswith('거래 0건')
    assert summarize(trade[:2], [], 1)['liquidity_flag'].startswith('거래 3건 미만')


def test_lawd_cd_table_is_five_digits():
    assert all(len(v) == 5 and v.isdigit() for v in LAWD_CD.values())
    assert LAWD_CD['서울 금천구'] == '11545'


def test_parse_naver_price():
    assert parse_naver_price('6,000') == 60_000_000
    assert parse_naver_price('1억') == 100_000_000
    assert parse_naver_price('1억 5,000') == 150_000_000
    assert parse_naver_price('<b>2억</b> 7,000') == 270_000_000
    assert parse_naver_price('') is None
    assert parse_naver_price('문의') is None


def test_calculate_gap():
    g = calculate_gap({'sale': {'avg': 110}, 'jeonse': {'avg': 77}}, 100, 120)
    assert g['naver_vs_molit_pct'] == 10.0
    assert g['naver_vs_apsl_pct'] == -8.3
    assert g['jeonse_rate_pct'] == 70.0
    g = calculate_gap({'sale': {'avg': None}, 'jeonse': {'avg': None}}, None, None)
    assert all(v is None for v in g.values())


def test_parse_onbid_response_variants():
    assert parse_onbid_response({'header': {'resultCode': '03', 'resultMsg': 'NODATA'}}) == ([], None)
    assert parse_onbid_response({'result': {'resultCode': '00', 'resultMsg': 'DB_ERROR'}}) == ([], None)
    items, err = parse_onbid_response({'header': {'resultCode': '30', 'resultMsg': 'KEY'}})
    assert items is None and '30' in err
    items, _ = parse_onbid_response({'header': {'resultCode': '00'}, 'body': {'items': {'item': {'a': 1}}}})
    assert items == [{'a': 1}]
    items, _ = parse_onbid_response({'header': {'resultCode': '00'}, 'body': {'items': ''}})
    assert items == []


def test_format_price():
    assert format_price(42_400_000) == '4,240만'
    assert format_price(424_000_000) == '4.24억'
    assert format_price(100_000_000) == '1억'
    assert format_price(None) == '-' and format_price(0) == '0'
