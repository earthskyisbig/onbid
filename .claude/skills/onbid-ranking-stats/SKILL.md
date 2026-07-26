---
name: onbid-ranking-stats
description: 온비드(OnBid) 순위물건목록(조회수·관심물건·저감률 순위), 부동산 물건목록, 물건 입찰결과상세, 용도별 입찰통계 Open API를 호출하는 스킬. "인기물건", "조회수 순위", "관심물건 순위", "저감률 순위", "낙찰 통계", "용도별 통계", "입찰결과", "낙찰가율" 등의 요청 시 반드시 이 스킬을 사용할 것.
---

# 온비드 순위·통계 조회 스킬

## API 구성 (2026-07-26 활용신청 승인, 실제 호출로 검증 완료)

| 서비스 | 오퍼레이션 | 용도 | 필수 파라미터 |
|--------|-----------|------|--------------|
| `OnbidInqRnkClgSrvc` | `getInqRnkClg` | 조회수 순위 | `cltrDivNm` (부동산\|동산\|자동차) |
| `OnbidItrsCltrRnkClgSrvc` | `getItrsCltrRnkClg` | 관심물건 순위 (최근 1주일) | `cltrDivNm` |
| `Onbid50PctDecrCltrSrvc` | `get50PctDecrCltr` | 저감률 순위 | `cltrDivNm` |
| `OnbidRlstListSrvc2` | `getRlstCltrList2` | 부동산 물건목록 (입찰중/입찰예정) | `prptDivCd`, `pvctTrgtYn` |
| `OnbidCltrBidRsltDtlSrvc2` | `getCltrBidRsltDtl2` | 물건 입찰결과상세 (낙찰/유찰/취소) | `cltrMngNo` |
| `OnbidUsgBidStatsSrvc` | `getKamcoCltrUsgStats` / `getOrgCltrUsgStats` | 용도별 입찰통계 (캠코/이용기관) | `statsTypeCd`+`inqPerd` / `inqPerd` |

**API 기반 URL**: `https://apis.data.go.kr/B010003/`
**인증**: serviceKey (.env의 `ONBID_API_KEY`, Decoding 키 원문 그대로 — 코드가 unquote() 적용하므로 Encoding/Decoding 둘 다 동작하나 Decoding 권장)
**응답 루트**: `data['header']` + `data['body']` (rc=00 정상, rc=03 NODATA, rc=11 필수파라미터 누락)

주의: `getInqRnkClg`/`getItrsCltrRnkClg`/`get50PctDecrCltr` 셋 다 요청 파라미터는 `cltrDivNm` 하나뿐이지만, 실제 응답 아이템에는 `cltrMngNo`, `apslEvlAmt`, `lowstBidPrcIndctCont`, `pbctStatCd` 등 상세 필드가 함께 옴 — 별도 상세조회 없이 바로 활용 가능.

---

## 실행 방법

```bash
# 조회수 순위 (부동산/동산/자동차 중 선택)
python3 scripts/fetch_ranking_stats.py inq-rank --cltr-div 부동산 --rows 20

# 관심물건 순위 (최근 1주일 관심등록 많은 순)
python3 scripts/fetch_ranking_stats.py interest-rank --cltr-div 부동산 --rows 20

# 저감률 순위 (감정가 대비 최저입찰가 할인폭 큰 순)
python3 scripts/fetch_ranking_stats.py discount-rank --cltr-div 부동산 --rows 20

# 부동산 물건목록 (입찰중/입찰예정, 재산유형·수의계약가능여부 필수)
python3 scripts/fetch_ranking_stats.py rlst-list \
    --prpt-div 0007 --pvct-trgt N \
    --region-sido 경기도 --region-sggu 수원시 --rows 50

# 물건 입찰결과상세 (낙찰/유찰/취소 이력 — cltrMngNo 필요)
python3 scripts/fetch_ranking_stats.py bid-result --cltr-mng-no 2024-1100-084555

# 용도별 입찰통계 — 캠코 관리물건 (재산유형 통계코드 필수)
python3 scripts/fetch_ranking_stats.py usg-stats --scope kamco --stats-type 0044 --period 2024

# 용도별 입찰통계 — 이용기관 물건
python3 scripts/fetch_ranking_stats.py usg-stats --scope org --period 2024

# 결과를 JSON으로 저장하려면 --output 추가
python3 scripts/fetch_ranking_stats.py inq-rank --cltr-div 부동산 --output _workspace/inq_rank.json
```

---

## 파라미터 참고

### 순위 3종 공통 (`--cltr-div`)
`부동산` | `동산` | `자동차` — 정확히 이 3개 문자열만 허용 (부분 매칭 안 됨)

### rlst-list (`--prpt-div`)
재산유형코드, 복수는 쉼표로 구분(`0007,0005`):
`0007`압류재산 `0010`국유재산 `0005`기타일반재산 `0004`불용품 `0002`공유재산
`0003`금융권담보재산 `0006`유입재산 `0008`수탁재산 `0011`공공개발재산 `0013`파산재산

`--pvct-trgt`: `Y`(수의계약가능) / `N`(수의계약불가) — 필수

### usg-stats (`--stats-type`, kamco 스코프 필수)
`0041`압류재산 `0044`국유재산 `0045`수탁/유입자산 `0046`공유재산
`--period`: 연도별 `2024`, 월별 `202403`, 분기별 `2024-1`

낙찰가율이 200% 이상이거나 25% 미만인 물건은 통계 왜곡 방지를 위해 산정에서 제외됨(원 API 사양).

---

## 응답 코드 처리

| 코드 | 메시지 | 대응 |
|------|--------|------|
| 00 | NORMAL_CODE | 정상 |
| 03 | NODATA_ERROR | 해당 조건 데이터 없음 — 정상 케이스로 skip |
| 11 | NO_MANDATORY_REQUEST_PARAMETERS_ERROR | 필수 파라미터 누락 확인 |
| 22 | LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR | 요청 제한 초과, 대기 후 재시도 |
| 30 | SERVICE_KEY_IS_NOT_REGISTERED_ERROR | `.env`의 `ONBID_API_KEY` 확인 |

---

## 다른 스킬과의 관계

- 물건 상세 전체 정보(권리관계, 감정평가서, 등기사항 등)가 필요하면 `onbid-search` 스킬의 상세조회(`OnbidRlstDtlSrvc2`)로 넘어갈 것. 이 스킬의 순위/통계 API는 요약 정보만 제공.
- `cltrMngNo`를 이 스킬로 먼저 확보한 뒤 `onbid-search`나 `bid-analysis`로 이어서 분석하는 흐름을 권장.
