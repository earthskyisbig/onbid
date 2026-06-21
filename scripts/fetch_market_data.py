#!/usr/bin/env python3
"""
경기도 필터링 아파트 10건 — 매매 실거래가 + 전월세 데이터 조회
APIs: RTMSDataSvcAptTradeDev (매매) + RTMSDataSvcAptRent (전월세)
"""
import requests, json, os, time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import unquote
from dotenv import load_dotenv

load_dotenv('/Users/leo-myung/onbid/.env')
KEY = unquote(os.getenv('MOLIT_API_KEY', ''))

# 대상 아파트 목록 (단지명 키워드, LAWD_CD, 지역명)
TARGETS = [
    {"no": 1,  "keyword": "청북이지더원",        "lawd_cd": "41220", "region": "평택 청북읍",  "area": 75.83, "apsl": 2.54},
    {"no": 2,  "keyword": "보평역서희스타힐스",   "lawd_cd": "41461", "region": "용인 처인구",  "area": 71.29, "apsl": 4.80},
    {"no": 3,  "keyword": "우림그린빌리지",       "lawd_cd": "41590", "region": "화성 기안동",  "area": 83.39, "apsl": 2.70},
    {"no": 4,  "keyword": "우주마루",             "lawd_cd": "41370", "region": "오산 원동",    "area": 67.64, "apsl": 1.60},
    {"no": 5,  "keyword": "덕계역금강펜테리움",   "lawd_cd": "41630", "region": "양주 덕계동",  "area": 59.30, "apsl": 3.39},
    {"no": 6,  "keyword": "유승한내들",           "lawd_cd": "41480", "region": "파주 검산동",  "area": 59.78, "apsl": 1.54},
    {"no": 7,  "keyword": "푸르지오",             "lawd_cd": "41113", "region": "수원 권선구",  "area": 84.96, "apsl": 4.25},
    {"no": 8,  "keyword": "세원",                 "lawd_cd": "41463", "region": "용인 기흥구",  "area": 59.50, "apsl": 1.97},
]

# 최근 6개월
def recent_months(n=6):
    months = []
    dt = datetime.now()
    for _ in range(n):
        months.append(dt.strftime("%Y%m"))
        dt -= timedelta(days=32)
        dt = dt.replace(day=1)
    return months

MONTHS = recent_months(6)
print(f"조회 기간: {MONTHS[-1]} ~ {MONTHS[0]}")

def xml_items(xml_text):
    """XML 응답에서 item 리스트 반환"""
    try:
        root = ET.fromstring(xml_text)
        items = root.findall('.//item')
        return items
    except Exception as e:
        print(f"  XML 파싱 오류: {e}")
        return []

def get_text(item, tag):
    el = item.find(tag)
    return el.text.strip() if el is not None and el.text else ''

def fetch_trade(lawd_cd, deal_ymd):
    """매매 실거래가 조회 (RTMSDataSvcAptTradeDev)"""
    url = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
    params = {
        'serviceKey': KEY,
        'LAWD_CD': lawd_cd,
        'DEAL_YMD': deal_ymd,
        'pageNo': 1,
        'numOfRows': 1000,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        # Dev 엔드포인트 실패시 기본 엔드포인트로 fallback
        if r.status_code != 200 or '<resultCode>30</resultCode>' in r.text:
            url2 = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
            r = requests.get(url2, params=params, timeout=15)
        return r.text
    except Exception as e:
        print(f"  매매 API 오류: {e}")
        return ''

def fetch_rent(lawd_cd, deal_ymd):
    """전월세 실거래가 조회 (RTMSDataSvcAptRent)"""
    url = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"
    params = {
        'serviceKey': KEY,
        'LAWD_CD': lawd_cd,
        'DEAL_YMD': deal_ymd,
        'pageNo': 1,
        'numOfRows': 1000,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        return r.text
    except Exception as e:
        print(f"  전월세 API 오류: {e}")
        return ''

results = {}

for target in TARGETS:
    no = target['no']
    keyword = target['keyword']
    lawd_cd = target['lawd_cd']
    region = target['region']
    area = target['area']
    apsl = target['apsl']

    print(f"\n[{no}] {region} {keyword} (감정가 {apsl}억, 면적 {area}㎡)")

    trade_records = []
    rent_records = []

    for ym in MONTHS:
        time.sleep(0.2)

        # 매매
        xml = fetch_trade(lawd_cd, ym)
        for item in xml_items(xml):
            apt_nm = get_text(item, 'aptNm')
            if keyword not in apt_nm:
                continue
            area_val = float(get_text(item, 'excluUseAr') or 0)
            if abs(area_val - area) > 5:  # 면적 ±5㎡ 허용
                continue
            trade_records.append({
                'type': '매매',
                'aptNm': apt_nm,
                'excluUseAr': area_val,
                'dealAmount': get_text(item, 'dealAmount'),
                'dealYMD': f"{get_text(item,'dealYear')}-{get_text(item,'dealMonth').zfill(2)}-{get_text(item,'dealDay').zfill(2)}",
                'floor': get_text(item, 'floor'),
                'buildYear': get_text(item, 'buildYear'),
                'umdNm': get_text(item, 'umdNm'),
                'dealingGbn': get_text(item, 'dealingGbn'),
            })

        # 전월세
        xml = fetch_rent(lawd_cd, ym)
        for item in xml_items(xml):
            apt_nm = get_text(item, 'aptNm')
            if keyword not in apt_nm:
                continue
            area_val = float(get_text(item, 'excluUseAr') or 0)
            if abs(area_val - area) > 5:
                continue
            monthly = get_text(item, 'monthlyRent')
            rent_type = '월세' if monthly and monthly != '0' else '전세'
            rent_records.append({
                'type': rent_type,
                'aptNm': apt_nm,
                'excluUseAr': area_val,
                'deposit': get_text(item, 'deposit'),
                'monthlyRent': monthly,
                'dealYMD': f"{get_text(item,'dealYear')}-{get_text(item,'dealMonth').zfill(2)}-{get_text(item,'dealDay').zfill(2)}",
                'floor': get_text(item, 'floor'),
                'buildYear': get_text(item, 'buildYear'),
                'umdNm': get_text(item, 'umdNm'),
                'contractTerm': get_text(item, 'contractTerm'),
            })

    # 금액 파싱 (만원 → 억원)
    def parse_amt(s):
        return round(int(s.replace(',', '')) / 10000, 2) if s and s != '' else None

    for r in trade_records:
        r['dealAmount_억'] = parse_amt(r['dealAmount'])
    for r in rent_records:
        r['deposit_억'] = parse_amt(r['deposit'])

    # 요약 통계
    trade_amts = [r['dealAmount_억'] for r in trade_records if r['dealAmount_억']]
    jeonse_deps = [r['deposit_억'] for r in rent_records if r['type'] == '전세' and r['deposit_억']]

    summary = {
        'no': no,
        'region': region,
        'keyword': keyword,
        'area': area,
        'apsl_amt': apsl,
        'trade_count': len(trade_records),
        'trade_avg_억': round(sum(trade_amts)/len(trade_amts), 2) if trade_amts else None,
        'trade_max_억': max(trade_amts) if trade_amts else None,
        'trade_min_억': min(trade_amts) if trade_amts else None,
        'jeonse_count': len([r for r in rent_records if r['type'] == '전세']),
        'jeonse_avg_억': round(sum(jeonse_deps)/len(jeonse_deps), 2) if jeonse_deps else None,
        'wolse_count': len([r for r in rent_records if r['type'] == '월세']),
    }
    if summary['trade_avg_억']:
        margin = round(summary['trade_avg_억'] - apsl, 2)
        summary['vs_apsl_억'] = margin
        summary['vs_apsl_pct'] = round(margin / apsl * 100, 1)

    results[str(no)] = {
        'summary': summary,
        'trade': trade_records,
        'rent': rent_records,
    }

    # 출력
    t = summary
    print(f"  매매: {t['trade_count']}건 | 평균 {t['trade_avg_억']}억 | 최고 {t['trade_max_억']}억 | 최저 {t['trade_min_억']}억")
    print(f"  전세: {t['jeonse_count']}건 | 평균 {t['jeonse_avg_억']}억 | 월세: {t['wolse_count']}건")
    if t.get('vs_apsl_억') is not None:
        sign = '+' if t['vs_apsl_억'] >= 0 else ''
        print(f"  시세 vs 감정가: {sign}{t['vs_apsl_억']}억 ({sign}{t['vs_apsl_pct']}%)")

# 저장
out_path = '/Users/leo-myung/onbid/_workspace/market_data_20260621.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\n\n{'='*60}")
print("[ 경기도 10개 아파트 시세 요약 ]")
print(f"{'='*60}")
print(f"{'No':>2} {'지역':12} {'단지':14} {'감정가':>5} {'매매평균':>7} {'차이':>7} {'전세평균':>7}")
print('-'*60)
for k, v in results.items():
    s = v['summary']
    trade_avg = f"{s['trade_avg_억']}억" if s['trade_avg_억'] else '데이터無'
    jeonse_avg = f"{s['jeonse_avg_억']}억" if s['jeonse_avg_억'] else '데이터無'
    diff = f"{s['vs_apsl_억']:+.2f}억" if s.get('vs_apsl_억') is not None else '-'
    print(f"{s['no']:>2} {s['region']:12} {s['keyword']:14} {s['apsl_amt']:>4.2f}억 {trade_avg:>7} {diff:>7} {jeonse_avg:>7}")

print(f"\n결과 저장: {out_path}")
