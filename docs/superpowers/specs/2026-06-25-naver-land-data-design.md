# 네이버 부동산 호가 조회 스킬 설계

**날짜**: 2026-06-25  
**목적**: 공매 물건의 낙찰 후 출구 전략 수립을 위해 네이버 부동산 현재 매매·전세·월세 호가를 수집하고 국토부 실거래가와의 괴리율을 계산한다.

---

## 1. 전체 구조

새 스킬 `naver-land-data`를 신규 생성하고 `location-analysis` Step 2.5로 통합한다.

```
location-analysis 파이프라인
  Step 1: 주소 파싱
  Step 2: MOLIT 실거래가 (기존)
  Step 2.5: 네이버 호가 조회 (신규) ← naver-land-data 스킬 호출
  Step 3: 개발호재 조사
  Step 4: 종합 평가
```

naver-land-data 내부 흐름:
```
입력: 단지명 키워드 + 시도/시군구 + 전용면적 + 감정가 + MOLIT 실거래 평균
  ↓
[경로 A] Naver 모바일 API 직접 호출
  m.land.naver.com/search → complexId 획득
  /complex/getComplexArticleList (매매, tradTpCd=A1)
  /complex/getComplexArticleList (전세 B1, 월세 B2)
  ↓ (403/429/빈 결과 시)
[경로 B] anti_bot_scraper subprocess fallback
  github.com/HarimxChoi/anti_bot_scraper
  ↓
괴리율 계산 → 저장
```

---

## 2. 입출력 스키마

### 입력
```python
{
  "apt_keyword": "일신아파트",
  "lctnSdnm": "경기도",
  "lctnSggnm": "포천시",
  "target_area": 49.92,        # 전용면적 ㎡
  "apsl_amt": 90500000,        # 감정가 (원)
  "molit_trade_avg": 95000000, # MOLIT 실거래 평균 (원, 없으면 None)
  "cltrMngNo": "2026-0200-106923"
}
```

### 출력 `_workspace/naver_listings_{cltrMngNo}.json`
```json
{
  "complex_name": "일신아파트",
  "complex_id": "12345",
  "scope": "same_complex",
  "fetched_at": "2026-06-25 09:00",
  "sale": {
    "count": 3,
    "avg_price": 105000000,
    "min_price": 98000000,
    "max_price": 115000000,
    "listings": [
      {"price": 105000000, "area": 49.92, "floor": "7", "direction": "남", "agent": ""}
    ]
  },
  "jeonse": {
    "count": 2,
    "avg_price": 72000000,
    "listings": []
  },
  "wolse": {
    "count": 1,
    "deposit": 10000000,
    "monthly": 350000,
    "listings": []
  },
  "gap_analysis": {
    "naver_vs_molit_pct": 10.5,
    "naver_vs_apsl_pct": 16.0,
    "jeonse_rate_pct": 68.5
  }
}
```

---

## 3. API 호출 명세

### 경로 A: Naver 모바일 API

| 단계 | URL | 파라미터 |
|------|-----|---------|
| 단지 검색 | `GET https://m.land.naver.com/search/result/{query}` | query = "단지명 시군구" |
| 매매 매물 | `GET https://m.land.naver.com/complex/getComplexArticleList` | complexNo, tradTpCd=A1, page |
| 전세 매물 | 동일 | tradTpCd=B1 |
| 월세 매물 | 동일 | tradTpCd=B2 |

**필수 헤더:**
```python
headers = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Referer": "https://m.land.naver.com/",
    "Accept": "application/json",
}
```

**면적 필터:** `target_area ± 10㎡`  
**rate limit:** 호출 간 `time.sleep(random.uniform(0.5, 1.5))`

### 경로 B: anti_bot_scraper fallback

- 조건: A에서 403 / 429 / 연속 3회 빈 결과 시 자동 전환
- 실행: `subprocess.run(['python3', 'anti_bot_scraper/main.py', ...])`
- 결과를 동일 스키마로 정규화

---

## 4. 에러 처리

| 상황 | 대응 |
|------|------|
| A 차단 (403/429) | 경로 B로 즉시 전환 |
| 단지 검색 결과 없음 | scope를 `neighborhood`로 확장 (동일 시군구 + 유사 면적) |
| B도 실패 | 빈 결과 저장, `gap_analysis: null`, 경고 출력 후 파이프라인 계속 |
| 매물 0건 | 동일 시군구 내 유사 면적 다른 단지로 확장, `scope: neighborhood` 표기 |

---

## 5. 신규 파일 목록

| 파일 | 역할 |
|------|------|
| `.claude/skills/naver-land-data/SKILL.md` | 스킬 정의 |
| `scripts/fetch_naver_listings.py` | 실제 크롤링 스크립트 |
| `anti_bot_scraper/` | fallback 크롤러 (git clone) |

**수정 파일:**
- `.claude/skills/location-analysis/SKILL.md` — Step 2.5 추가
- `.claude/agents/location-analyst.md` — naver-land-data 호출 로직 추가

---

## 6. 괴리율 계산 공식

```
naver_vs_molit_pct = (naver_sale_avg - molit_trade_avg) / molit_trade_avg * 100
naver_vs_apsl_pct  = (naver_sale_avg - apsl_amt) / apsl_amt * 100
jeonse_rate_pct    = jeonse_avg / naver_sale_avg * 100
```

양수 = 호가가 실거래/감정가보다 높음 (매도 여유 있음)  
음수 = 호가가 실거래/감정가보다 낮음 (주의)
