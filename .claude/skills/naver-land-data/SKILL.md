---
name: naver-land-data
description: 네이버 부동산 현재 매매·전세·월세 호가를 단지명+법정동코드로 조회하고 감정가·국토부 실거래가 대비 괴리율을 계산한다. "네이버 호가", "현재 시세", "매물 가격", "전세가율", "호가 vs 실거래" 요청 시 이 스킬을 사용할 것.
---

# 네이버 부동산 호가 조회 스킬

## 사용 시점
location-analysis Step 2.5에서 MOLIT 실거래가 조회(Step 2) 직후 호출한다.  
아파트 물건에만 적용 (토지·상업용은 스킵).

## 실행

### 기본 실행
```bash
python3 scripts/fetch_naver_listings.py \
    --keyword "{apt_keyword}" \
    --lawd-cd "{lawd_cd_5자리}" \
    --area {target_area} \
    --apsl {apsl_amt} \
    --molit-avg {molit_trade_avg_또는_생략} \
    --cltr-mng-no "{cltrMngNo}"
```

### 파라미터
| 파라미터 | 설명 | 예시 |
|---------|------|------|
| `--keyword` | 단지명 키워드 (아파트 제외 가능) | `일신`, `푸르지오` |
| `--lawd-cd` | 5자리 법정동코드 | `41650` |
| `--area` | 전용면적 ㎡ | `49.92` |
| `--apsl` | 감정가 (원) | `90500000` |
| `--molit-avg` | MOLIT 실거래 평균 (원, 선택) | `95000000` |
| `--cltr-mng-no` | 물건관리번호 (파일명용) | `2026-0200-106923` |

## 출력
`_workspace/naver_listings_{cltrMngNo}.json`:

```json
{
  "fetched_at": "2026-06-25 09:00",
  "method": "direct_api",
  "complex_name": "일신",
  "complex_id": "13966",
  "scope": "same_complex",
  "sale":   {"count": 12, "avg": 80000000, "min": 60000000, "max": 100000000},
  "jeonse": {"count": 0,  "avg": null, "min": null, "max": null},
  "wolse":  {"count": 4},
  "gap_analysis": {
    "naver_vs_molit_pct": -15.8,
    "naver_vs_apsl_pct":  -11.6,
    "jeonse_rate_pct": null
  }
}
```

## scope 의미
- `same_complex`: 동일 단지 매물 기반
- `neighborhood`: 단지 미발견 → 시군구 전체 확장
- `not_found`: 매물 없음

## 괴리율 해석
- `naver_vs_molit_pct` 양수: 호가 > 실거래 → 시세 상승 추세
- `naver_vs_molit_pct` 음수: 호가 < 실거래 → 주의 (시세 하락 가능성)
- `naver_vs_apsl_pct` 양수: 호가 > 감정가 → 낙찰 후 즉시 시세차익 가능
- `jeonse_rate_pct` 70% 이상: 갭투자 위험 낮음

## 전세 가격 참고
Naver `/cluster/ajax/complexList` 엔드포인트는 매매 가격만 제공하며, 거래유형(B1 전세)으로 조회해도 가격 필드는 매매가와 동일.  
전세 가격이 필요하면 별도 개별 매물 API 접근 필요 (현재 미구현).

## 에러 처리
- 403/429 차단: 로그 출력 후 예외 전파 (차단 시 재시도 또는 수동 조회 필요)
- 단지 미발견 (`scope=not_found`): 빈 sale 데이터, gap_analysis 전체 null 저장 후 계속
