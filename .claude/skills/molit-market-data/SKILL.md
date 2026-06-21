---
name: molit-market-data
description: 국토교통부 아파트 매매·전월세 실거래가 API로 시세를 조회하는 스킬. 공매 물건 분석 시 감정가 대비 시세 검증, 전세가율 산출, 유동성 확인에 사용. "실거래가", "시세 조회", "전세가", "매매가", "MOLIT API", "시세 분석", "감정가 비교" 요청 시 반드시 이 스킬을 사용할 것. 단일 물건 및 복수 물건 배치 조회 모두 지원.
---

# 국토부 실거래가 조회 스킬

## API 정보

| 구분 | 매매 실거래가 | 전월세 실거래가 |
|------|-------------|--------------|
| 엔드포인트 | `https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev` | `https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent` |
| 인증 | `.env`의 `MOLIT_API_KEY` (URL 인코딩키 → `unquote()` 후 전달) | 동일 |
| 응답 형식 | **XML** (JSON 지원 안 함) | XML |
| 필수 파라미터 | `serviceKey`, `LAWD_CD` (5자리), `DEAL_YMD` (YYYYMM) | 동일 |

## LAWD_CD 경기도 주요 코드표

```python
LAWD_CD = {
    # 수원시
    '수원 장안구': '41110', '수원 권선구': '41113', '수원 팔달구': '41115', '수원 영통구': '41117',
    # 성남·용인
    '성남 수정구': '41131', '성남 중원구': '41133', '성남 분당구': '41135',
    '용인 처인구': '41461', '용인 기흥구': '41463', '용인 수지구': '41465',
    # 기타 경기
    '평택': '41220', '오산': '41370', '시흥': '41390', '의왕': '41430',
    '하남': '41450', '파주': '41480', '화성': '41590', '광주': '41610',
    '양주': '41630', '안양 만안구': '41171', '안양 동안구': '41173',
    '광명': '41210', '과천': '41290', '안산 상록구': '41271', '안산 단원구': '41273',
    # 서울
    '서울 강남구': '11680', '서울 서초구': '11650', '서울 송파구': '11710',
    '서울 마포구': '11440', '서울 강동구': '11740',
}
```

지역명에서 LAWD_CD를 추론할 수 없으면 `www.code.go.kr` 에서 법정동코드 10자리 중 앞 5자리 사용.

## 실행 절차

### Step 1: 입력 확인
물건 분석 요청에서 다음을 추출:
- `apt_keyword`: 단지명 키워드 (예: "덕계역금강펜테리움", "푸르지오1단지")
- `lawd_cd`: 지역코드 (위 테이블 참조)
- `target_area`: 목표 전용면적 (㎡)
- `apsl_amt`: 감정가 (억 단위, 비교용)
- `months`: 조회 개월 수 (기본값 12)

면적 필터: `abs(거래면적 - target_area) <= 5` ㎡ 허용. 데이터가 없으면 `<= 10`으로 확장 재시도.

### Step 2: API 호출 코드

```python
import requests, os, time
import xml.etree.ElementTree as ET
from urllib.parse import unquote
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv('/Users/leo-myung/onbid/.env')
KEY = unquote(os.getenv('MOLIT_API_KEY', ''))

def recent_months(n=12):
    months, dt = [], datetime.now()
    for _ in range(n):
        months.append(dt.strftime("%Y%m"))
        dt = (dt.replace(day=1) - timedelta(days=1)).replace(day=1)
    return months

def xml_items(xml_text):
    try:
        return ET.fromstring(xml_text).findall('.//item')
    except:
        return []

def get_text(item, tag):
    el = item.find(tag)
    return el.text.strip() if el is not None and el.text else ''

def fetch_api(endpoint_path, lawd_cd, deal_ymd):
    url = f"https://apis.data.go.kr/1613000/{endpoint_path}"
    r = requests.get(url, params={
        'serviceKey': KEY, 'LAWD_CD': lawd_cd,
        'DEAL_YMD': deal_ymd, 'pageNo': 1, 'numOfRows': 1000,
    }, timeout=15)
    return r.text

def query_apt(apt_keyword, lawd_cd, target_area, months=12, area_tol=5):
    """단일 단지 매매+전월세 조회. 반환: (trade_list, rent_list)"""
    trade_all, rent_all = [], []
    for ym in recent_months(months):
        time.sleep(0.2)
        # 매매
        for item in xml_items(fetch_api(
            "RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev", lawd_cd, ym)):
            if apt_keyword not in get_text(item, 'aptNm'):
                continue
            ar = float(get_text(item, 'excluUseAr') or 0)
            if abs(ar - target_area) > area_tol:
                continue
            trade_all.append({
                'aptNm':      get_text(item, 'aptNm'),
                'area':       ar,
                'dealAmount': get_text(item, 'dealAmount'),
                'dealAmt_억': round(int(get_text(item,'dealAmount').replace(',','') or 0)/10000, 2),
                'dealYMD':    f"{get_text(item,'dealYear')}-{get_text(item,'dealMonth').zfill(2)}-{get_text(item,'dealDay').zfill(2)}",
                'floor':      get_text(item, 'floor'),
                'buildYear':  get_text(item, 'buildYear'),
                'dealingGbn': get_text(item, 'dealingGbn'),
            })
        # 전월세
        for item in xml_items(fetch_api(
            "RTMSDataSvcAptRent/getRTMSDataSvcAptRent", lawd_cd, ym)):
            if apt_keyword not in get_text(item, 'aptNm'):
                continue
            ar = float(get_text(item, 'excluUseAr') or 0)
            if abs(ar - target_area) > area_tol:
                continue
            dep_str = get_text(item, 'deposit')
            mth_str = get_text(item, 'monthlyRent')
            rent_all.append({
                'aptNm':      get_text(item, 'aptNm'),
                'area':       ar,
                'type':       '월세' if mth_str and mth_str != '0' else '전세',
                'deposit':    dep_str,
                'deposit_억': round(int(dep_str.replace(',','') or 0)/10000, 2),
                'monthlyRent': mth_str,
                'dealYMD':    f"{get_text(item,'dealYear')}-{get_text(item,'dealMonth').zfill(2)}-{get_text(item,'dealDay').zfill(2)}",
                'buildYear':  get_text(item, 'buildYear'),
            })
    return trade_all, rent_all

def summarize(trade_list, rent_list, apsl_amt=None):
    """집계 통계 반환"""
    amts = [r['dealAmt_억'] for r in trade_list if r['dealAmt_억']]
    jeonse = [r['deposit_억'] for r in rent_list if r['type']=='전세' and r['deposit_억']]
    s = {
        'trade_count': len(trade_list),
        'trade_avg':   round(sum(amts)/len(amts), 2) if amts else None,
        'trade_max':   max(amts) if amts else None,
        'trade_min':   min(amts) if amts else None,
        'jeonse_count': len(jeonse),
        'jeonse_avg':  round(sum(jeonse)/len(jeonse), 2) if jeonse else None,
        'wolse_count': len([r for r in rent_list if r['type']=='월세']),
        'build_year':  next((r['buildYear'] for r in (trade_list+rent_list) if r.get('buildYear')), None),
    }
    if apsl_amt and s['trade_avg']:
        diff = round(s['trade_avg'] - apsl_amt, 2)
        s['vs_apsl_억'] = diff
        s['vs_apsl_pct'] = round(diff / apsl_amt * 100, 1)
        s['jeonse_ratio_pct'] = round(s['jeonse_avg'] / s['trade_avg'] * 100, 1) if s['jeonse_avg'] else None
    return s
```

### Step 3: 데이터 없음 처리

```python
# 면적 ±5㎡ 결과 0건이면 ±10㎡로 재시도
trade, rent = query_apt(keyword, lawd_cd, area, area_tol=5)
if not trade and not rent:
    trade, rent = query_apt(keyword, lawd_cd, area, area_tol=10)
    if not trade and not rent:
        # 12개월 → 24개월로 확장
        trade, rent = query_apt(keyword, lawd_cd, area, months=24, area_tol=10)
```

데이터가 여전히 없으면 보고서에 **"12~24개월간 거래 없음 — 유동성 위험"** 으로 명시하고 진행.

### Step 4: 결과 저장

단일 물건: `_workspace/market_{cltrMngNo}.json`  
배치 분석: `_workspace/market_data_{날짜}.json`

```python
import json
result = {
    'cltrMngNo': cltr_mng_no,
    'apt_keyword': apt_keyword,
    'lawd_cd': lawd_cd,
    'target_area': target_area,
    'query_months': months,
    'summary': summarize(trade, rent, apsl_amt),
    'trade': trade,
    'rent': rent,
}
with open(f'_workspace/market_{cltr_mng_no}.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
```

## 출력 형식 (보고서용)

```
[시세 분석] 덕계역금강펜테리움 59.3㎡ (양주시 덕계동, LAWD_CD: 41630)
조회 기간: 2025-07 ~ 2026-06 (12개월)

매매: 47건
  평균 3.31억 | 최고 3.5억 | 최저 2.97억
  건축년도: 2023년

전세: 16건 | 평균 2.32억 (전세가율 70%)
월세: 14건

감정가 대비: -0.08억 (-2.4%)  ← 감정가가 시세보다 2.4% 높음
최저입찰가(3.051억) 대비 시세: +0.26억 마진 존재
```

## 해석 기준

| 지표 | 해석 |
|------|------|
| 시세 > 감정가 | 할인 매수 효과 ✅ |
| 시세 < 감정가 × 90% (최저가) | 낙찰해도 시세 이하 구매 불가 ⚠️ |
| 거래건수 < 3건 | 통계 신뢰 부족 — 현장 추가 확인 필요 |
| 거래건수 = 0건 | 유동성 위험 — 출구 전략 제한 |
| 전세가율 ≥ 80% | 역전세 위험 ⚠️ |
| 전세가율 60~75% | 안정 구간 ✅ |

## 오케스트레이터 연동

`location-analysis` 스킬 Step 2에서 이 스킬을 호출한다.  
`bid-analysis` 스킬은 이 스킬의 `summary` 결과(`trade_avg`, `jeonse_avg`, `vs_apsl_pct`)를 입찰가 산정 근거로 사용한다.

출력 파일 경로: `_workspace/market_{cltrMngNo}.json`  
다음 단계 스킬: `bid-analysis`
