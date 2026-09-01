---
name: bid-analysis
description: 공매 물건의 입찰가를 산정하고 수익성을 분석하는 스킬. 감정평가 대비 할인율 계산, roi-calculator 스킬로 3가지 시나리오 수익성 분석, 리스크 정량화, 최적 입찰가 권고. "입찰가 산정", "수익성 분석", "ROI 계산", "얼마에 입찰", "투자 수익", "시나리오 분석" 등의 요청 시 반드시 이 스킬을 사용할 것.
---

# 입찰가 산정·수익성 분석 스킬

> **계산은 반드시 `scripts/roi_calculator.py scenarios` 로 한다.** LLM 이 암산·수식으로 ROI 를 만들지 않는다.
> 공식 정의: `.claude/skills/roi-calculator/references/auction-formulas.md` (스크립트가 그대로 구현, 테스트 `tests/test_roi_calculator.py`)

---

## 분석 절차

### Step 1: 입력 데이터 로드

```python
import json

def load_analysis_data(cltr_mng_no, workspace='_workspace'):
    doc = json.load(open(f'{workspace}/02_doc_analysis_{cltr_mng_no}.json', encoding='utf-8'))
    loc = json.load(open(f'{workspace}/02_location_analysis_{cltr_mng_no}.json', encoding='utf-8'))
    search = json.load(open(f'{workspace}/01_search_results.json', encoding='utf-8'))
    property_data = next(p for p in search['properties'] if p.get('cltrMngNo') == cltr_mng_no)
    return doc, loc, property_data
```

**roi_calculator 입력값 출처** (모두 원 단위)

| roi_calculator 파라미터 | 출처 | 필드 |
|------------------------|------|------|
| `--appraisal` (appraisalValue) | property_data | `apslEvlAmt` |
| `--min-bid` (minBidPrice) | property_data | `lowstBidPrc` (현재 회차). 다음 저감 회차 진입 전략이면 `rounds[n].lowstBidPrc` — 어느 회차인지 `--sale-basis` 메모에 명시 |
| `--assumed-rights` | doc | `rights_analysis.assumed_amount` / `property_statement.senior_claims` (미확인이면 생략 → 경고 발생) |
| `--eviction-cost` | doc | `eviction_risk.estimated_cost` |
| `--repair-cost` | doc | `condition.repair_estimate` |
| `--unpaid-mgmt-fee` | doc | `unpaid_management_fee` |
| `--fair-value` | Step 2 | 적정가치 |
| `--acq-tax-rate` | 물건 유형 | 아래 표 |
| `--loan`, `--loan-rate` | 사용자 입력 (기본 0) | |
| `--owner` | 사용자 입력 (기본 individual) | |

취득세율:
- 주택 1채·6억 이하 → `0.011` (전용 85㎡ 초과면 `0.013`)
- 주택 1채·6~9억 → `0.022` 내외 (구간별 누진), 9억 초과 → `0.033`
- 비주택(토지·상가·오피스텔 업무용) → `0.046`
- 다주택·조정지역은 8.8%~13.4% — 사용자 보유주택 수 확인 후 결정

---

### Step 2: 적정가치(fair_value) 산정

```python
def calculate_fair_value(appraisal_amount, loc_score, dev_bonus):
    """loc_score: 입지종합점수 1~5, dev_bonus: 개발호재 가중치 0.0~0.3 (02_location_analysis 결과)"""
    loc_factor = 0.8 + (loc_score / 5 * 0.4)   # 0.8~1.2
    return appraisal_amount * loc_factor * (1 + dev_bonus)
```

- `market_{cltrMngNo}.json` (molit-market-data) 의 `summary.trade_avg` 또는 `trade_median` 과 위 공식값 중 **더 보수적인(낮은) 값**을 fair_value 로 채택
- 실거래 0건이면 공식값을 쓰되 `--sale-basis "실거래 없음 — 공식값"` 으로 표기
- 네이버 호가(`naver_listings_*.json`)는 참고만 하고 fair_value 로 쓰지 않는다 (호가 ≠ 체결가)

---

### Step 3~5: 3시나리오 계산 + 권고 (스크립트 1회 호출)

```bash
python3 scripts/roi_calculator.py scenarios \
    --cltr-mng-no 2026-16156-004 \
    --appraisal 250000000 --min-bid 200000000 --fair-value 255000000 \
    --sale-basis "최근 12개월 ㎡당 중앙값 기준 2.55억(보수 채택), 038회차 최저가 진입" \
    --acq-tax-rate 0.011 --legal-fee 300000 --registration-fee 500000 \
    --eviction-cost 2000000 --repair-cost 3000000 --assumed-rights 0 \
    --output _workspace/03_bid_strategy_2026-16156-004.json
```

파라미터가 많으면 JSON 으로: `--json-in params.json` (키는 camelCase: `acquisitionTaxRate`, `evictionCost`, …). CLI 인자가 JSON 값을 덮어쓴다.

스크립트가 수행하는 것 (bid-analysis 규칙 그대로):

| 시나리오 | bidPrice | expectedSalePrice | 보유 |
|---------|----------|------------------|------|
| 🔵 보수 conservative | 최저가 × 1.00 | fair_value × 0.90 | 36개월 |
| 🟡 기준 base | 최저가 × 1.05 | fair_value × 1.00 | 24개월 |
| 🔴 공격 aggressive | 최저가 × 1.12 | fair_value × 1.10 | 18개월 |

판정 (기준 시나리오 연환산 ROI): ≥15% 적극입찰 / 10~15% 소극입찰 / <10% 보류
권고 입찰가 = min(공격 시나리오 bidPrice, fair_value × 0.85, 판정 구간 상한). 이 값이 최저가보다 낮으면 자동 **보류** + 경고.
리스크 정량화(명도지연·숨은권리·시장하락·수리비초과 기대비용)도 `risks` 에 포함된다.

---

### Step 6: 해석·보완 (LLM 의 역할)

스크립트 출력(`03_bid_strategy_{id}.json`)을 읽고 **수치는 바꾸지 않은 채** 다음을 같은 파일에 추가한다:

```json
{
  "propertyName": "...",
  "analysisNotes": {
    "fairValueBasis": "실거래/공식값 중 무엇을 왜 채택했는지",
    "roundStrategy": "현재 회차 vs 다음 저감 회차 진입 판단과 근거 (rounds 배열 인용)",
    "exitOptions": "매도 외 전세·월세 출구가 있으면 수치와 함께",
    "assumptions": ["취득세율 1.1% (1주택 가정)", "..."]
  },
  "qualitativeRisks": ["HUG 인수조건 확인 선행", "..."]
}
```

전세·월세 출구 수익률이 필요하면 `python3 scripts/roi_calculator.py gap ...` 을 별도 호출해 `exitOptions` 에 인용한다.

---

## 출력

`_workspace/03_bid_strategy_{cltrMngNo}.json` — `roi_calculator.py scenarios` 출력 스키마 + Step 6 추가 필드:

```json
{
  "cltrMngNo": "...", "generatedAt": "...", "generator": "scripts/roi_calculator.py scenarios",
  "appraisalValue": 0, "minBidPrice": 0, "fairValue": 0, "expectedSalePriceBasis": "...",
  "commonInputs": { "acquisitionTaxRate": 0.011, "...": "..." },
  "scenarios": {
    "conservative": { "label": "보수", "inputs": {...}, "bidToAppraisalRatio": 0, "costs": {...},
                      "totalAcquisitionCost": 0, "totalExitCost": 0, "totalFinanceCost": 0,
                      "netProfit": 0, "simpleROI": 0, "annualizedROI": 0, "warnings": [] },
    "base": { "..." }, "aggressive": { "..." }
  },
  "recommendation": { "verdict": "적극입찰|소극입찰|보류", "bidPrice": 0, "bidRange": [0, 0],
                      "referenceBidPrice": 0, "fairValueCap": 0, "baseAnnualizedROI": 0, "rationale": "..." },
  "risks": { "items": [ {"risk": "...", "probability": 0.2, "impact": 0, "expectedCost": 0} ], "expectedRiskCost": 0 },
  "warnings": [], "disclaimer": "...",
  "propertyName": "...", "analysisNotes": {...}, "qualitativeRisks": []
}
```

이 스키마여야 Phase 3.5 의 `scripts/verify_results.py phase3` 가 ROI 를 재계산해 대조할 수 있다.
