---
name: molit-market-data
description: 국토교통부 아파트 매매·전월세 실거래가 API로 시세를 조회하는 스킬. 공매 물건 분석 시 감정가 대비 시세 검증, 전세가율 산출, 유동성 확인에 사용. "실거래가", "시세 조회", "전세가", "매매가", "MOLIT API", "시세 분석", "감정가 비교" 요청 시 반드시 이 스킬을 사용할 것. 단일 물건 및 복수 물건 배치 조회 모두 지원.
---

# 국토부 실거래가 조회 스킬

구현체: `scripts/fetch_market_data.py` (CLI). 인라인 코드를 다시 쓰지 말고 스크립트를 호출한다.

## 물건 종류 (`--kind`, 2026-09-02 전부 승인·실호출 확인)

| kind | 대상 | API | 키워드 매칭 필드 | 면적 필드 | 전월세 |
|------|------|-----|----------------|----------|-------|
| `apt` (기본) | 아파트 | AptTradeDev(+AptTrade) / AptRent | aptNm | excluUseAr | ○ |
| `offi` | 오피스텔 | OffiTrade / OffiRent | offiNm | excluUseAr | ○ |
| `rh` | 연립·다세대 | RHTrade / RHRent | mhouseNm(건물명) | excluUseAr | ○ |
| `sh` | 단독·다가구 | SHTrade / SHRent | umdNm, houseType | totalFloorAr | ○ |
| `land` | 토지 | LandTrade | umdNm, jimok, landUse | dealArea | × |
| `shop` | 상업·업무용 | NrgTrade | umdNm, buildingUse, buildingType | buildingAr | × |

온비드 `cltrUsgSclsCtgrNm` → kind: 아파트→apt, 오피스텔→offi, 다세대주택·연립주택→rh, 단독주택·다가구→sh, 대지·임야·전·답→land, 근린생활시설·상가·사무실→shop.
`land`/`shop` 은 ㎡당 중앙값(`price_per_sqm_median`)과 대상 면적 환산가(`implied_value_at_target_area`)를 내며, 감정가·최저가 비교는 환산가 기준이다. 면적 편차가 크므로 `--area-tol` 을 넉넉히(토지 ±300~500㎡).

## API 정보

| 구분 | 매매 | 전월세 |
|------|------|--------|
| 엔드포인트 | `RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev` (실패 시 `RTMSDataSvcAptTrade` 폴백) | `RTMSDataSvcAptRent/getRTMSDataSvcAptRent` |
| 인증 | `.env`의 `MOLIT_API_KEY` | 동일 |
| 응답 | XML 전용. `resultCode` 000/00 외는 오류로 기록 | XML |
| 필수 | `LAWD_CD`(5자리), `DEAL_YMD`(YYYYMM) | 동일 |

계약해제 건(`cdealType=O`)은 매매 통계에서 제외한다.

## 실행

```bash
# 단일 물건 (모든 금액은 원 단위)
python3 scripts/fetch_market_data.py \
    --keyword 덕계역금강펜테리움 --lawd-cd 41630 --area 59.3 \
    --apsl 339000000 --low-bid 305100000 --cltr-mng-no 2026-0200-106923

# 지역명으로 코드 지정 가능 (스크립트 내 LAWD_CD 표: 경기 전역 + 서울 25구)
python3 scripts/fetch_market_data.py --kind offi --keyword 메트로타운 --lawd-cd "서울 금천구" --area 25.41
python3 scripts/fetch_market_data.py --kind rh --keyword 호안빌 --lawd-cd "서울 은평구" --area 39.94
python3 scripts/fetch_market_data.py --kind land --keyword 검천리 --lawd-cd 41610 --area 500 --area-tol 400

# 배치
python3 scripts/fetch_market_data.py --batch targets.json   # [{"cltr_mng_no","keyword","lawd_cd","area","apsl","low_bid"}, ...]
```

| 옵션 | 기본 | 설명 |
|------|------|------|
| `--months` | 12 | 조회 개월 |
| `--area-tol` | 5 | 전용면적 허용 오차(㎡) |
| `--no-expand` | off | 0건일 때 자동 확장(±10㎡ → 24개월) 끄기 |
| `--output` | `_workspace/market_{cltrMngNo}.json` | 저장 경로 |

표에 없는 지역의 법정동코드는 `www.code.go.kr` 10자리 중 앞 5자리.

## 단지명 키워드 잡는 법
- 물건명에서 아파트 단지명만 추출: "양주시 덕계동 123 덕계역금강펜테리움 101동 501호" → `덕계역금강펜테리움`
- API `aptNm` 은 부분일치이므로 너무 짧은 키워드("푸르지오")는 다른 단지가 섞인다 → 결과 `trade[].aptNm` 을 확인해 필요하면 키워드를 길게
- 다세대·오피스텔·토지·상가는 `--kind` 를 바꿔 조회한다 (apt 로 조회하면 0건). `rh`/`sh` 는 건물명이 등록되지 않은 경우가 많으니 0건이면 키워드를 읍면동명으로 바꿔 지역 시세라도 확보

## 출력 (`_workspace/market_{cltrMngNo}.json`)

```json
{
  "fetched_at": "...", "kind": "apt", "kind_label": "아파트", "apt_keyword": "...", "lawd_cd": "41630", "target_area": 59.3,
  "apsl_amt": 339000000, "low_bid": 305100000,
  "query_months": 12, "area_tol": 5.0, "period": "202510 ~ 202609",
  "summary": {
    "trade_count": 47, "trade_avg": 331000000, "trade_median": 330000000, "trade_max": 350000000, "trade_min": 297000000,
    "trade_latest": "2026-08-21", "jeonse_count": 16, "jeonse_avg": 232000000, "wolse_count": 14, "build_year": "2023",
    "trade_avg_억": 3.31, "jeonse_avg_억": 2.32,
    "jeonse_ratio_pct": 70.1, "vs_apsl": -8000000, "vs_apsl_pct": -2.4, "vs_lowbid": 25900000, "vs_lowbid_pct": 8.5,
    "liquidity_flag": "OK"
  },
  "trade": [ {"aptNm": "...", "area": 59.3, "dealAmount": 331000000, "dealYMD": "2026-08-21", "floor": "12", "buildYear": "2023", "dealingGbn": "중개거래"} ],
  "rent":  [ {"type": "전세", "deposit": 232000000, "monthlyRent": 0, "dealYMD": "...", "contractTerm": "..."} ],
  "errors": []
}
```

`bid-analysis` 는 `summary.trade_avg`/`trade_median` 을 fair_value 후보로, `jeonse_avg` 를 갭 출구 계산에 쓴다.

## 해석 기준

| 지표 | 해석 |
|------|------|
| 시세 > 감정가 (`vs_apsl_pct` > 0) | 할인 매수 효과 ✅ |
| 시세 < 최저입찰가 (`vs_lowbid_pct` < 0) | 낙찰해도 시세 이하 매수 불가 ⚠️ |
| `liquidity_flag` ≠ OK | 거래 3건 미만: 통계 신뢰 부족 / 0건: 유동성 위험 — 보고서에 그대로 표기 |
| `jeonse_ratio_pct` ≥ 80 | 역전세 위험 ⚠️ / 60~75 안정 ✅ |

## 오케스트레이터 연동
`location-analysis` Step 2 에서 호출 → `02_location_analysis_{id}.json` 의 `market_data` 에 `summary` 를 복사 → `bid-analysis` 가 사용.
