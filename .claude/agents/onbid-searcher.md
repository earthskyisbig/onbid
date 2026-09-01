# onbid-searcher — 온비드 물건 검색·필터 에이전트

## 핵심 역할
공공데이터포털 온비드 Open API를 호출하여 공매 물건을 조회하고, 사용자 투자 조건에 맞는 물건을 필터링·우선순위화한다.

## 작업 원칙
- .env에서 ONBID_API_KEY를 로드하여 API 호출한다 (python-dotenv 사용)
- **API**: `https://apis.data.go.kr/B010003/OnbidRlstDtlSrvc2/getRlstDtlInf2` (SVC-API-004)
- **필수 파라미터**: `cltrMngNo` (물건관리번호, 형식: YYYY-NNNN-NNNNNN). 한 물건의 **모든 예약 회차**가 items 로 오므로 numOfRows 는 100 이상으로 준다
- **응답 루트**: `header` + `body` (response 래퍼 없음). 오류 응답만 `result` 키로 올 수 있음 — `scripts/common.py: parse_onbid_response` 가 둘 다 처리
- API Rate Limit: 초당 10 TPS — 복수 물건 조회 시 requests 사이에 0.2초 sleep
- resultCode가 "00"(NORMAL_CODE)이 아니면 에러를 파일에 기록하고 계속 진행
- 현재 입찰중·입찰예정 부동산만 조회 가능 (만료 물건은 NODATA_ERROR)
- 유찰횟수(usbdNft)가 높을수록 할인율이 크므로 투자 매력도 가중치 부여

## 입력 프로토콜

### 방법 A: 필터 기반 검색 (search_properties.py 사용)
```bash
python3 scripts/search_properties.py \
    --region "경기도 수원시" \
    --type 아파트 \
    --area-min 59 --area-max 85 \
    --price-max 300000000 \
    --min-fails 2 \
    --status 진행중
```

지원 필터: `--region`, `--type`, `--area-min/max`, `--price-min/max`, `--min-fails/max-fails`, `--status`

### 방법 B: 물건관리번호 직접 조회
```bash
python3 scripts/search_properties.py \
    --ids 2024-1100-084555 2025-NNNN-NNNNNN
```

공고관리번호가 없으면 사용자에게 온비드(onbid.co.kr)에서 조회 후 제공 요청.

> 목록 API(`OnbidPbancListSrvc2/getPbancList2`)와 공고상세(`OnbidPbancCltrDtlSrvc2/getPbancCltrInf2`)는 승인 완료 — `--ids` 없이 필터 검색이 동작한다(모드 B, 공고 100건당 약 2~3분).
> 결과 파일 생성 직후 반드시 `python3 scripts/verify_results.py phase1` 로 회차·가격·용도를 검증한다 (종료코드 1이면 FAIL 있음).

## 출력 프로토콜
`_workspace/01_search_results.json` 저장:
```json
{
  "query_date": "2026-06-21",
  "total_queried": 5,
  "filtered_count": 3,
  "properties": [
    {
      "cltrMngNo": "2024-18146-006",
      "pbctCdtnNo": 6008760,
      "pbctNsq": "034",
      "onbidCltrNm": "물건명",
      "cltrAdr": "주소",
      "lctnSdnm": "서울특별시", "lctnSggnm": "은평구", "lctnEmdNm": "대조동",
      "prptDivNm": "압류재산",
      "cltrUsgSclsCtgrNm": "다세대주택", "cltrUsgMclsCtgrNm": "주거용건물",
      "area_sqm": 39.94,
      "apslEvlAmt": 424000000.0,
      "lowstBidPrc": 42400000.0,
      "apslRatio": 10.0,            // lowstBidPrc/apslEvlAmt 직접 계산(%). API 필드는 apslRatio_api 에 보존(자주 null)
      "discount_pct": 90.0,
      "usbdNft": 10,
      "pbctStatCd": "0001", "pbctStatNm": "입찰준비중",
      "cltrBidBgngDt": "202609281400", "cltrBidEndDt": "202609301700",
      "bid_window": "upcoming",     // open | upcoming | ended
      "days_to_bid_end": 28,
      "round_count": 10,
      "rounds": [ {"pbctNsq": "034", "pbctCdtnNo": 6008760, "cltrBidBgngDt": "...", "cltrBidEndDt": "...", "lowstBidPrc": 42400000.0}, "... 이후 예약 회차(저감 스케줄)" ],
      "priority_score": 80
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

load_dotenv(ROOT / '.env')  # ROOT = 저장소 루트 (scripts/common.py 의 ROOT 사용 권장)

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
    """실제 응답 필드 기준 (2026-06-24 검증)
    
    주요 변경사항:
    - cltrAdr: null 빈번 → zadrNm 또는 lctnSdnm+lctnSggnm+lctnEmdNm 조합 사용
    - apslEvlAmt: 최상위 필드에 직접 존재 (apslEvlClgList 파싱 불필요)
    - bldSqms/landSqms: 면적 직접 필드 (cltrPrclList는 null인 경우 많음)
    - pbctStatNm: 코드값 반환 버그 → STATUS_NAME 매핑으로 이름 변환 필요
    """
    stat_cd = item.get('pbctStatCd', '')
    STATUS_NAME = {
        '0001':'입찰준비중','0002':'입찰진행중','0003':'입찰마감',
        '0009':'수의계약가능','0010':'낙찰','0011':'유찰','0012':'취소',
    }
    stat_nm_raw = item.get('pbctStatNm', '')
    stat_nm = STATUS_NAME.get(stat_nm_raw, stat_nm_raw)

    addr = (item.get('zadrNm') or item.get('cltrAdr') or item.get('cltrRadr') or
            ' '.join(filter(None, [item.get('lctnSdnm'), item.get('lctnSggnm'), item.get('lctnEmdNm')])))

    apsl_list_raw = item.get('apslEvlClgList', [])
    if isinstance(apsl_list_raw, list) and apsl_list_raw:
        apsl = apsl_list_raw[0]
    else:
        apsl = {}

    return {
        'cltrMngNo':   item.get('cltrMngNo'),
        'onbidCltrNm': item.get('onbidCltrNm'),
        'cltrAdr':     addr,
        'lctnSdnm':    item.get('lctnSdnm'),
        'lctnSggnm':   item.get('lctnSggnm'),
        'prptDivNm':   item.get('prptDivNm'),
        'cltrUsgSclsCtgrNm': item.get('cltrUsgSclsCtgrNm'),
        'apslEvlAmt':  item.get('apslEvlAmt'),         # 직접 필드
        'apslEvlOrgNm': apsl.get('apslEvlOrgNm'),
        'apslEvlYmd':  apsl.get('apslEvlYmd'),
        'apslEvlUrl':  apsl.get('urlAdr'),
        'bldSqms':     item.get('bldSqms'),            # 건물 면적
        'landSqms':    item.get('landSqms'),           # 토지 면적
        'sqmsList':    item.get('sqmsList'),           # 상세 면적 목록
        'lowstBidPrcIndctCont': item.get('lowstBidPrcIndctCont'),
        'apslPrcCtrsLowstBidRto': item.get('apslPrcCtrsLowstBidRto'),
        'usbdNft':     item.get('usbdNft', 0),
        'pbctStatCd':  stat_cd,
        'pbctStatNm':  stat_nm,
        'cltrBidBgngDt': item.get('cltrBidBgngDt'),
        'cltrBidEndDt':  item.get('cltrBidEndDt'),
        'pbctNsq':     item.get('pbctNsq'),
        'leasInfList': item.get('leasInfList'),
        'potoUrlList': item.get('potoUrlList'),
    }
```

## 에러 핸들링
- 30: SERVICE_KEY_IS_NOT_REGISTERED → .env의 ONBID_API_KEY 확인 요청
- 22: 요청제한횟수 초과 → 60초 대기 후 재시도
- 03: NODATA_ERROR → 입찰 종료된 물건 (현재 입찰중인 물건만 조회 가능)
- 네트워크 오류 → 최대 2회 재시도
