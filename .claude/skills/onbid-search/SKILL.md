---
name: onbid-search
description: 온비드(OnBid) 공공데이터 Open API를 호출하여 공매 물건 정보를 검색·조회·필터링하는 스킬. 지역/용도/면적/가격/유찰횟수로 필터 검색, 물건관리번호(cltrMngNo)로 상세 조회, API 결과를 구조화된 JSON으로 저장. "온비드 조회", "공매 검색", "물건 찾기", "지역 검색", "아파트 검색", "유찰 물건" 등의 요청 시 반드시 이 스킬을 사용할 것.
---

# 온비드 물건 검색 스킬

## API 구성

| 서비스 | 엔드포인트 | 상태 | 용도 |
|--------|-----------|------|------|
| 상세조회 (SVC-004) | `OnbidRlstDtlSrvc2/getRlstDtlInf2` | ✅ 구독 중 | cltrMngNo로 단건/배치 조회 |
| 공고목록 (목록API) | `OnbidPbancListSrvc/getPbancList` | ⚠️ 별도 구독 필요 | 필터 기반 목록 검색 |

**API 기반 URL**: `https://apis.data.go.kr/B010003/`
**인증**: serviceKey (공공데이터포털, .env의 `ONBID_API_KEY` — URL-decoded 필수)
**응답 루트**: `data['header']` + `data['body']` (response 래퍼 없음, 2026-06-21 검증)

---

## 검색 방법 선택

### 방법 A: 필터 기반 검색 (search_properties.py)
지역·용도·면적·가격·유찰횟수 지정 → 자동 검색

```bash
# 기본 사용법
python3 /Users/leo-myung/onbid/scripts/search_properties.py \
    --region "경기도 수원시" \
    --type 아파트 \
    --area-min 59 --area-max 85 \
    --price-max 300000000 \
    --min-fails 2

# 물건관리번호 직접 지정 (목록API 없이도 작동)
python3 /Users/leo-myung/onbid/scripts/search_properties.py \
    --ids 2026-0200-106923 2026-0200-106925 \
    --region "경기도"
```

### 방법 B: 코드로 직접 조회 (cltrMngNo 알고 있을 때)
```python
import requests, os
from dotenv import load_dotenv
from urllib.parse import unquote

load_dotenv('/Users/leo-myung/onbid/.env')
KEY = unquote(os.getenv('ONBID_API_KEY', ''))

def fetch_property(cltr_mng_no):
    url = "https://apis.data.go.kr/B010003/OnbidRlstDtlSrvc2/getRlstDtlInf2"
    r = requests.get(url, params={
        'serviceKey': KEY,
        'pageNo': 1, 'numOfRows': 10, 'resultType': 'json',
        'cltrMngNo': cltr_mng_no
    }, timeout=10)
    data = r.json()
    header = data.get('header', {})
    if header.get('resultCode') != '00':
        return None, header.get('resultMsg')
    items = data.get('body', {}).get('items', {}).get('item', [])
    return (items if isinstance(items, list) else [items]), None
```

---

## 필터 파라미터 전체 목록

| 파라미터 | 설명 | 예시 |
|---------|------|------|
| `--region` | 지역 (시도 또는 "시도 시군구") | `"경기도"`, `"경기도 수원시"`, `"서울특별시 강남구"` |
| `--type` | 용도 키워드 | `아파트`, `토지`, `상가`, `오피스텔`, `임야`, `공장`, `창고` |
| `--area-min` | 면적 하한 (㎡) | `59` |
| `--area-max` | 면적 상한 (㎡) | `85` |
| `--price-min` | 최저입찰가 하한 (원) | `100000000` (=1억) |
| `--price-max` | 최저입찰가 상한 (원) | `500000000` (=5억) |
| `--min-fails` | 유찰횟수 최소 | `2` |
| `--max-fails` | 유찰횟수 최대 | `10` |
| `--status` | 입찰상태 (`진행중`/`예정`/`모두`) | `진행중` (기본: 모두) |
| `--ids` | 물건관리번호 직접 지정 | `2026-0200-106923 2026-0200-106925` |
| `--rows` | 페이지당 결과 수 | `100` (기본값) |
| `--output` | 저장 경로 | `_workspace/01_search_results.json` |

---

## 목록 API 구독 방법 (최초 1회)

현재 API 키는 상세조회(SVC-004)만 구독됨.  
`--ids` 없이 필터만으로 검색하려면 목록 API 추가 구독 필요:

1. https://www.data.go.kr 접속 → 로그인
2. 검색: `한국자산관리공사 온비드 공고목록`
3. **한국자산관리공사_온비드 공고목록 조회서비스** → 활용신청
4. 승인 후 (보통 즉시~1일) `.env`의 `ONBID_API_KEY`로 자동 사용

구독 전까지는 `--ids` 옵션 또는 onbid.co.kr 수동 검색으로 번호 획득 후 조회 가능.

---

## 물건관리번호 없을 때 안내

1. https://www.onbid.co.kr 접속
2. 물건검색 → 지역/재산유형/가격 조건 설정
3. 관심 물건 클릭 → 상세 페이지 상단의 **물건관리번호** 복사 (형식: `YYYY-NNNN-NNNNNN`)
4. `--ids` 옵션에 복사한 번호 나열

---

## 응답 코드 처리

| 코드 | 메시지 | 대응 |
|------|--------|------|
| 00 | NORMAL_CODE | 정상 처리 |
| 03 | NODATA_ERROR | 입찰 종료 물건 — 스킵 |
| 11 | NO_MANDATORY_PARAMS | cltrMngNo 누락 — 파라미터 확인 |
| 22 | LIMITED_REQUESTS | 60초 대기 후 재시도 |
| 30 | KEY_NOT_REGISTERED | ONBID_API_KEY 확인 |

---

## 핵심 응답 필드

| 필드명 | 설명 | 비고 |
|--------|------|------|
| `cltrMngNo` | 물건관리번호 | |
| `cltrAdr` | 물건주소 | 지역 필터에 사용 |
| `cltrUsgSclsCtgrNm` | 용도소분류명 | 아파트, 임야, 창고시설 등 |
| `lowstBidPrcIndctCont` | 최저입찰가 | 가격 필터에 사용 |
| `apslPrcCtrsLowstBidRto` | 감정가 대비 최저입찰가 비율 | |
| `usbdNft` | 유찰횟수 | |
| `pbctStatCd` | 입찰상태코드 | 0001=준비중, 0002=진행중 |
| `cltrPrclList` | 면적정보 리스트 | `cltrPrclAr` 합산으로 총면적 계산 |
| `apslEvlClgList` | 감정평가정보 | `[0].apslEvlAmt` = 감정평가금액 |

---

## 우선순위 점수 산정

- 유찰횟수 × 10점 (최대 50점)
- 감정가 대비 최저입찰가 비율: 50% 미만 +30점, 70% 미만 +20점, 80% 미만 +10점
- 입찰 마감 7일 이내 +10점
