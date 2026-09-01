---
name: onbid-search
description: 온비드(OnBid) 공공데이터 Open API를 호출하여 공매 물건 정보를 검색·조회·필터링하는 스킬. 지역/용도/면적/가격/유찰횟수로 필터 검색, 물건관리번호(cltrMngNo)로 상세 조회, API 결과를 구조화된 JSON으로 저장. "온비드 조회", "공매 검색", "물건 찾기", "지역 검색", "아파트 검색", "유찰 물건" 등의 요청 시 반드시 이 스킬을 사용할 것.
---

# 온비드 물건 검색 스킬

## API 구성 (전부 승인·검증 완료)

| 단계 | 엔드포인트 | 용도 |
|------|-----------|------|
| 목록 | `OnbidPbancListSrvc2/getPbancList2` | 압류재산(prptDivCd=0007) 공고 전체 수집(약 3,000행 → 고유 공고 약 360건). **반복 횟수는 예약 회차 수이지 유찰이 아니다** |
| 공고→물건 | `OnbidPbancCltrDtlSrvc2/getPbancCltrInf2` | pbancMngNo → cltrMngNo 목록 (지역·용도·가격 사전필터) |
| 상세 | `OnbidRlstDtlSrvc2/getRlstDtlInf2` | cltrMngNo 로 상세. **한 물건의 모든 예약 회차가 items 로 옴** |

**기반 URL**: `https://apis.data.go.kr/B010003/`
**인증**: `.env`의 `ONBID_API_KEY` (Encoding/Decoding 둘 다 가능 — `scripts/common.py: get_key` 가 unquote)
**응답 루트**: `header` + `body` (response 래퍼 없음). 오류 시 `result` 키로 올 수 있음 → `common.parse_onbid_response` 가 처리
**호출 간격**: 상세/공고 호출 사이 1초 sleep, 429 는 Retry-After 대기 후 재시도 (common.onbid_get)

---

## 검색 방법

### 방법 A: 필터 검색 (모드 B, 목록 API 3단계)
```bash
python3 scripts/search_properties.py \
    --region "경기도 수원시" --type 아파트 \
    --area-min 59 --area-max 85 --price-max 300000000 --min-fails 2
```
공고 100건 처리에 약 2~3분. `--max-pbanc` 로 처리 공고 수 조절.

### 방법 B: 물건관리번호 직접 조회 (모드 A)
```bash
python3 scripts/search_properties.py --ids 2026-0200-106923 2026-0200-106925 --region "경기도"
```

### 검색 직후 필수: 검증
```bash
python3 scripts/verify_results.py phase1          # 회차·가격·용도 검증 (종료코드 1 = FAIL)
```

### 코드에서 직접 조회할 때
```python
import sys; sys.path.insert(0, 'scripts')
from common import onbid_get
from search_properties import select_current_round, normalize_item

rounds, err = onbid_get('OnbidRlstDtlSrvc2', 'getRlstDtlInf2', {'cltrMngNo': '2024-18146-006'}, rows=100)
current = select_current_round(rounds)             # 종료되지 않은 회차 중 가장 이른 회차
item = normalize_item(current, rounds=rounds)      # 통일 스키마 (아래 참조)
```

---

## 필터 파라미터

| 파라미터 | 설명 | 예시 |
|---------|------|------|
| `--region` | 지역 (시도 또는 "시도 시군구") | `"경기도"`, `"경기도 수원시"`, `"서울특별시 강남구"` |
| `--type` | 용도 키워드 (소분류명 부분일치) | `아파트`, `다세대`, `토지`, `상가`, `오피스텔`, `임야`, `공장`, `창고` |
| `--area-min/max` | 면적 (㎡). 면적 미상 물건은 통과 | `59`, `85` |
| `--price-min/max` | 최저입찰가 (원) | `100000000`, `500000000` |
| `--min-fails/max-fails` | 유찰횟수 | `2`, `10` |
| `--status` | `진행중`(0002) / `예정`(0001) / `모두` | 기본 `모두` |
| `--ids` | 물건관리번호 직접 지정 | `2026-0200-106923 ...` |
| `--rows` | 상세조회 numOfRows (회차 누락 방지) | 기본 `100` |
| `--max-pbanc` | 모드 B 처리 공고 수 | 기본 `100` |
| `--output` | 저장 경로 | 기본 `_workspace/01_search_results.json` |

`--type ""`(빈 문자열)은 필터 없음으로 처리한다 (66ab3f7 회귀 방지 테스트 있음).

**유찰횟수는 단계2의 물건별 `usbdNft` 로만 거른다.** 2026-09-02 실측: 공고목록에서 2회만 등장한 공고의 물건이 실제 유찰 4~6회, 10회 반복 공고 253건은 예약 회차. 이전 코드는 반복 횟수로 1단계에서 걸러 실제 유찰 물건을 놓쳤다.

---

## 회차 선택 원칙 (절대 규칙)

온비드 압류재산은 **향후 회차를 미리 여러 개 예약**해 둔다(매주 10%p 저감 등). 따라서:
- `pbctNsq`(회차번호) 최댓값 = 가장 먼 미래의 최다할인 회차 → **절대 "현재가"로 쓰지 않는다** (2026-07-26 사고)
- 현재 회차 = `cltrBidEndDt`가 아직 지나지 않은 회차 중 `cltrBidBgngDt`가 가장 이른 회차 (`select_current_round`)
- 전체 일정은 결과의 `rounds` 배열에 남긴다 → 다음 회차 진입 전략은 이 배열로 세운다

---

## 출력 스키마 (`_workspace/01_search_results.json`)

```json
{
  "query_date": "2026-09-02 12:00",
  "round_policy": "earliest cltrBidBgngDt among rounds whose cltrBidEndDt >= query_date",
  "filters": {"region": "...", "type": "...", "...": "..."},
  "total_fetched": 2, "filtered_count": 2,
  "properties": [{
    "cltrMngNo": "2024-18146-006", "pbctCdtnNo": 6008760, "pbctNsq": "034",
    "onbidCltrNm": "...", "cltrAdr": "...", "lctnSdnm": "서울특별시", "lctnSggnm": "은평구", "lctnEmdNm": "대조동",
    "prptDivNm": "압류재산", "cltrUsgSclsCtgrNm": "다세대주택", "cltrUsgMclsCtgrNm": "주거용건물",
    "area_sqm": 39.94,
    "apslEvlAmt": 424000000.0, "lowstBidPrc": 42400000.0,
    "apslRatio": 10.0, "apslRatio_api": null, "discount_pct": 90.0,
    "usbdNft": 10, "pbctStatCd": "0001", "pbctStatNm": "입찰준비중",
    "cltrBidBgngDt": "202609281400", "cltrBidEndDt": "202609301700",
    "bid_window": "upcoming", "days_to_bid_end": 28,
    "round_count": 10,
    "rounds": [{"pbctNsq": "034", "pbctCdtnNo": 6008760, "cltrBidBgngDt": "...", "cltrBidEndDt": "...", "pbctStatCd": "0001", "lowstBidPrc": 42400000.0}],
    "priority_score": 80
  }],
  "errors": []
}
```

| 필드 | 비고 |
|------|------|
| `apslRatio` | **직접 계산** `lowstBidPrc / apslEvlAmt × 100`. API 의 `apslPrcCtrsLowstBidRto` 는 상세조회에서 대부분 null 이라 신뢰하지 않는다 (2026-09-02 수정 전에는 null→100% 로 오기록됨) |
| `area_sqm` | `bldSqms` > `landSqms` > `sqmsList[0]` 순 |
| `apslEvlAmt` | 최상위 `apslEvlAmt` 우선, 없으면 `apslEvlClgList` 평균 |
| `pbctStatNm` | API 가 코드값을 돌려주는 버그 → 이름으로 변환 |
| `cltrAdr` | `zadrNm` > `cltrAdr` > `cltrRadr` > 시도+시군구+읍면동 |

---

## 우선순위 점수
- 유찰횟수 × 10점 (최대 50점)
- 감정가 대비 최저입찰가 비율: 50% 미만 +30, 70% 미만 +20, 80% 미만 +10
- 입찰 마감 7일 이내 +10

---

## 응답 코드 처리

| 코드 | 메시지 | 대응 |
|------|--------|------|
| 00 | NORMAL_CODE | 정상 |
| 03 | NODATA_ERROR | 입찰 종료 물건 — 정상 skip |
| 11 | NO_MANDATORY_PARAMS | cltrMngNo 누락 |
| 22 | LIMITED_REQUESTS | 60초 대기 후 재시도 |
| 30 | KEY_NOT_REGISTERED | ONBID_API_KEY 확인 |

## 물건관리번호 없을 때
1. https://www.onbid.co.kr → 물건검색 → 조건 설정
2. 상세 페이지 상단의 **물건관리번호** (형식 `YYYY-NNNN-NNNNNN`) 복사 → `--ids`
3. 또는 `onbid-ranking-stats` 스킬의 순위/목록 API 로 cltrMngNo 확보
