---
name: onbid-search
description: 온비드(OnBid) 공공데이터 Open API를 호출하여 공매 물건 정보를 검색·조회·필터링하는 스킬. 물건관리번호(cltrMngNo)로 부동산 물건 상세 조회, 재산유형/입찰상태/가격 조건으로 필터링, API 결과를 구조화된 JSON으로 저장. "온비드 조회", "공매 검색", "물건 찾기", "물건관리번호 조회", "입찰 목록" 등의 요청 시 반드시 이 스킬을 사용할 것.
---

# 온비드 물건 검색 스킬

## API 정보
- **서비스**: 한국자산관리공사_차세대 온비드 부동산 물건상세 조회서비스 (SVC-API-004)
- **URL**: `https://apis.data.go.kr/B010003/OnbidRlstDtlSrvc2/getRlstDtlInf2`
- **인증**: serviceKey (공공데이터포털 발급키, .env에서 로드)
- **방식**: REST GET, JSON 응답
- **Rate Limit**: 10 TPS
- **응답 루트**: `result` (주의: `response`가 아님)
- **제약**: 현재 입찰중·입찰예정 부동산만 조회 가능

## 필수 파라미터
| 파라미터 | 설명 | 예시 |
|---------|------|------|
| `cltrMngNo` | 물건관리번호 (필수) | `2024-1100-084555` |
| `pbctCdtnNo` | 공매조건번호 (옵션) | `3621804` |

## 실행 절차

### Step 1: 환경 준비
```bash
pip install requests python-dotenv 2>/dev/null | tail -1
```

### Step 2: API 호출 스크립트 실행
```python
import requests, json, os, time
from dotenv import load_dotenv

load_dotenv('/Users/leo-myung/onbid/.env')

def fetch_property(cltr_mng_no, pbct_cdtn_no=None, page_no=1, num_of_rows=10):
    url = "https://apis.data.go.kr/B010003/OnbidRlstDtlSrvc2/getRlstDtlInf2"
    params = {
        'serviceKey': os.getenv('ONBID_API_KEY'),
        'pageNo': page_no,
        'numOfRows': num_of_rows,
        'resultType': 'json',
        'cltrMngNo': cltr_mng_no
    }
    if pbct_cdtn_no:
        params['pbctCdtnNo'] = pbct_cdtn_no
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    # 실제 응답 구조: data['header'], data['body'] (response 래퍼 없음, 2026-06-21 검증)
    header = data.get('header', {})
    body = data.get('body', {})
    return header, body

def filter_properties(items, criteria):
    filtered = []
    for item in (items if isinstance(items, list) else [items]):
        # 입찰진행중(0002) 또는 입찰준비중(0001)만
        if item.get('pbctStatCd') not in ['0001', '0002']:
            continue
        # 매각(0001)만
        if criteria.get('sale_only') and item.get('dspsMthodCd') != '0001':
            continue
        # 지역 필터
        region = criteria.get('region', '')
        if region and region not in item.get('cltrAdr', ''):
            continue
        # 가격 필터
        max_price = criteria.get('max_price')
        if max_price and float(item.get('lowstBidPrcIndctCont', 0) or 0) > max_price:
            continue
        # 우선순위 점수
        score = 0
        score += min(int(item.get('usbdNft', 0)), 5) * 10
        ratio = float(item.get('apslPrcCtrsLowstBidRto', 100) or 100)
        if ratio < 50: score += 30
        elif ratio < 70: score += 20
        elif ratio < 80: score += 10
        item['priority_score'] = score
        filtered.append(item)
    return sorted(filtered, key=lambda x: x['priority_score'], reverse=True)
```

### Step 3: 결과 저장
결과를 `_workspace/01_search_results.json`에 저장한다.

## 물건관리번호가 없을 때
사용자에게 다음을 안내한다:
1. https://www.onbid.co.kr 접속
2. 물건 검색 (지역/재산유형 필터 적용)
3. 관심 물건 클릭 → 상세 페이지에서 **물건관리번호** 복사 (형식: YYYY-NNNN-NNNNNN)
4. 해당 번호 목록을 제공하면 API로 상세 분석

## 응답 코드 처리
- 00: 정상 → 진행
- 03: 데이터없음 → 해당 번호 스킵
- 22: 요청제한 초과 → 60초 대기 후 재시도
- 30: 미등록 서비스키 → ONBID_API_KEY 확인 요청
- 기타: 에러 기록 후 다음 공고 처리

## 핵심 응답 필드 참조
`references/api-spec.md` 참조
