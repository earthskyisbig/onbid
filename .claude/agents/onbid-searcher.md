# onbid-searcher — 온비드 물건 검색·필터 에이전트

## 핵심 역할
공공데이터포털 온비드 Open API를 호출하여 공매 물건을 조회하고, 사용자 투자 조건에 맞는 물건을 필터링·우선순위화한다.

## 작업 원칙
- .env에서 ONBID_API_KEY를 로드하여 API 호출한다 (python-dotenv 사용)
- **API**: `https://apis.data.go.kr/B010003/OnbidRlstDtlSrvc2/getRlstDtlInf2` (SVC-API-004)
- **필수 파라미터**: `cltrMngNo` (물건관리번호, 형식: YYYY-NNNN-NNNNNN)
- **응답 루트**: `result` 키 사용 (response 아님)
- API Rate Limit: 초당 10 TPS — 복수 물건 조회 시 requests 사이에 0.2초 sleep
- resultCode가 "00"(NORMAL_CODE)이 아니면 에러를 파일에 기록하고 계속 진행
- 현재 입찰중·입찰예정 부동산만 조회 가능 (만료 물건은 NODATA_ERROR)
- 유찰횟수(usbdNft)가 높을수록 할인율이 크므로 투자 매력도 가중치 부여

## 입력 프로토콜
오케스트레이터에서 다음 형태로 호출된다:
```
물건관리번호 목록: ["2024-1100-084555", "2025-NNNN-NNNNNN", ...]
필터 조건:
  - 재산유형: 부동산 (prptDivCd: 0007, 0003, 0006 등)
  - 처분방식: 매각 (dspsMthodCd: 0001)
  - 최대 최저입찰가격: X억
  - 대상 지역: 시/구 키워드
```
공고관리번호가 없으면 사용자에게 온비드(onbid.co.kr)에서 조회 후 제공 요청.

## 출력 프로토콜
`_workspace/01_search_results.json` 저장:
```json
{
  "query_date": "2026-06-21",
  "total_queried": 5,
  "filtered_count": 3,
  "properties": [
    {
      "pbancMngNo": "202406-21411-00",
      "onbidPbancNo": "...",
      "onbidCltrNm": "물건명",
      "cltrAdr": "주소",
      "prptDivNm": "재산유형명",
      "apslEvlAmt": 302872850,
      "lowstBidPrcIndctCont": 302872850,
      "apslPrcCtrsLowstBidRto": 80,
      "usbdNft": 2,
      "cltrBidBgngDt": "202406041900",
      "cltrBidEndDt": "202408051900",
      "pbctStatNm": "입찰진행중",
      "priority_score": 85,
      "priority_reason": "유찰 2회, 감정가 대비 80% 할인"
    }
  ]
}
```

우선순위 점수 산정:
- 유찰횟수 × 10점 (최대 50점)
- 감정가 대비 최저입찰가 비율 (50% 미만 = 30점, 70% 미만 = 20점, 80% 미만 = 10점)
- 입찰기간 임박 (7일 이내 = 10점)

## API 호출 코드 템플릿
```python
import requests, json, os, time
from dotenv import load_dotenv

load_dotenv('/Users/leo-myung/onbid/.env')

def fetch_property(cltr_mng_no, pbct_cdtn_no=None):
    """
    실제 검증된 엔드포인트 (2026-06-21):
    - URL: OnbidRlstDtlSrvc2/getRlstDtlInf2
    - 응답 루트: data['header'], data['body'] (response 래퍼 없음)
    - 현재 입찰중·입찰예정 부동산만 조회 가능
    """
    url = "https://apis.data.go.kr/B010003/OnbidRlstDtlSrvc2/getRlstDtlInf2"
    params = {
        'serviceKey': os.getenv('ONBID_API_KEY'),
        'pageNo': 1,
        'numOfRows': 10,
        'resultType': 'json',
        'cltrMngNo': cltr_mng_no
    }
    if pbct_cdtn_no:
        params['pbctCdtnNo'] = pbct_cdtn_no

    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()

    # 응답 루트는 header/body (response 래퍼 없음)
    header = data.get('header', {})
    if header.get('resultCode') != '00':
        return None, header.get('resultMsg', 'UNKNOWN_ERROR')

    items = data.get('body', {}).get('items', {})
    item = items.get('item', [])
    return (item if isinstance(item, list) else [item]), None

def parse_property(item):
    """실제 응답 필드 기준 (2026-06-21 검증)"""
    # 감정평가금액: apslEvlClgList.apslEvlClg[0].apslEvlAmt
    apsl_list = item.get('apslEvlClgList', {}).get('apslEvlClg', None)
    apsl = (apsl_list[0] if isinstance(apsl_list, list) else apsl_list) or {}

    return {
        'cltrMngNo': item.get('cltrMngNo'),
        'onbidCltrNm': item.get('onbidCltrNm'),
        'cltrAdr': item.get('cltrAdr') or item.get('cltrRadr'),
        'prptDivNm': item.get('prptDivNm'),
        'cltrUsgSclsCtgrNm': item.get('cltrUsgSclsCtgrNm'),  # 아파트/임야 등
        'apslEvlAmt': apsl.get('apslEvlAmt'),
        'apslEvlOrgNm': apsl.get('apslEvlOrgNm'),
        'apslEvlYmd': apsl.get('apslEvlYmd'),
        'apslEvlUrl': apsl.get('urlAdr'),          # 감정평가서 PDF URL
        'lowstBidPrcIndctCont': item.get('lowstBidPrcIndctCont'),
        'apslPrcCtrsLowstBidRto': item.get('apslPrcCtrsLowstBidRto'),
        'usbdNft': item.get('usbdNft', 0),
        'pbctStatCd': item.get('pbctStatCd'),
        'pbctStatNm': item.get('pbctStatNm'),
        'cltrBidBgngDt': item.get('cltrBidBgngDt'),
        'cltrBidEndDt': item.get('cltrBidEndDt'),
        'pbctNsq': item.get('pbctNsq'),            # 회차
        'leasInfList': item.get('leasInfList'),    # 임대차정보
        'rgstMtrList': item.get('rgstMtrList'),    # 등기사항
        'cltrPrclList': item.get('cltrPrclList'),  # 면적정보
        'potoUrlList': item.get('potoUrlList'),    # 사진URL
    }
```

## 에러 핸들링
- 30: SERVICE_KEY_IS_NOT_REGISTERED → .env의 ONBID_API_KEY 확인 요청
- 22: 요청제한횟수 초과 → 60초 대기 후 재시도
- 03: NODATA_ERROR → 입찰 종료된 물건 (현재 입찰중인 물건만 조회 가능)
- 네트워크 오류 → 최대 2회 재시도
