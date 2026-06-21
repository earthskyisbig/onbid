---
name: bid-analysis
description: 공매 물건의 입찰가를 산정하고 수익성을 분석하는 스킬. 감정평가 대비 할인율 계산, roi-calculator 스킬로 3가지 시나리오 수익성 분석, 리스크 정량화, 최적 입찰가 권고. "입찰가 산정", "수익성 분석", "ROI 계산", "얼마에 입찰", "투자 수익", "시나리오 분석" 등의 요청 시 반드시 이 스킬을 사용할 것.
---

# 입찰가 산정·수익성 분석 스킬

> **의존 스킬**: `roi-calculator` — Step 3~4는 roi-calculator를 3회 호출하여 수행한다.
> roi-calculator 공식은 `.claude/skills/roi-calculator/references/auction-formulas.md` 참조.

---

## 분석 절차

### Step 1: 입력 데이터 로드

이전 분석 단계 결과를 로드한다.

```python
import json

def load_analysis_data(cltr_mng_no, workspace='_workspace'):
    doc = json.load(open(f'{workspace}/02_doc_analysis_{cltr_mng_no}.json'))
    loc = json.load(open(f'{workspace}/02_location_analysis_{cltr_mng_no}.json'))
    search = json.load(open(f'{workspace}/01_search_results.json'))
    property_data = next(
        p for p in search['properties']
        if p.get('cltrMngNo') == cltr_mng_no or p.get('pbancMngNo')
    )
    return doc, loc, property_data
```

**roi-calculator 입력에 필요한 값 추출**

| roi-calculator 파라미터 | 출처 | 필드 |
|------------------------|------|------|
| appraisalValue | property_data | apslEvlAmt (감정평가금액) |
| 최저입찰가 | property_data | lwstBdPrc |
| assumedRightsAmount | doc | rights_analysis.assumed_amount |
| evictionCost | doc | eviction_risk.estimated_cost |
| repairCost | doc | condition.repair_estimate |
| expectedSalePrice | loc | market_data.avg_sale_price (매매 시세 평균) |
| loanAmount | 사용자 입력 또는 0 |  |
| ownerType | 사용자 입력 (기본 'individual') |  |

---

### Step 2: 적정가치 산정

입지분석 결과로 적정가치(fair_value)를 계산한다. roi-calculator의 `expectedSalePrice` 기준값으로 사용.

```python
def calculate_fair_value(appraisal_amount, loc_score, dev_bonus):
    """
    loc_score: 입지종합점수 (1-5, location_analysis 결과)
    dev_bonus: 개발호재 가중치 (0.0~0.3, location_analysis 결과)
    """
    loc_factor = 0.8 + (loc_score / 5 * 0.4)  # 0.8~1.2
    return appraisal_amount * loc_factor * (1 + dev_bonus)
```

- `loc_score`, `dev_bonus`는 `02_location_analysis_{cltrMngNo}.json`에서 추출
- fair_value와 molit-market-data 실거래가 평균 중 **더 보수적인 값**을 `expectedSalePrice` 기준으로 채택

---

### Step 3~4: roi-calculator로 3개 시나리오 ROI 계산

`roi-calculator` 스킬 (auction 모드)을 **3회** 호출한다.
각 시나리오는 **입찰가(bidPrice)**와 **예상매도가(expectedSalePrice)**만 달리하고, 나머지 비용 파라미터는 동일하게 유지한다.

#### 시나리오 정의

| 시나리오 | bidPrice | expectedSalePrice | holdingPeriodMonths | 의도 |
|---------|----------|------------------|--------------------|----|
| 🔵 보수 | 최저입찰가 × 1.00 | fair_value × 0.90 | 36 | 최소 입찰, 시세 하락 방어 |
| 🟡 기준 | 최저입찰가 × 1.05 | fair_value × 1.00 | 24 | 적정 경쟁 입찰, 현재 시세 |
| 🔴 공격 | 최저입찰가 × 1.12 | fair_value × 1.10 | 18 | 적극 입찰, 단기 시세 상승 기대 |

#### roi-calculator 호출 공통 파라미터

```
ownerType: 'individual' (기본; 사용자가 명시하면 해당 값 사용)
appraisalValue: property_data.apslEvlAmt
acquisitionTaxRate: 주택 여부·가격·보유주택수에 따라 결정
  - 주택 1채·6억 이하 → 1.1%
  - 주택 1채·6~9억 → 2.2%
  - 주택 1채·9억 초과 → 3.3% + 지방교육세
  - 비주택(일반부동산) → 4.6%
legalFee: 300,000원 (기본)
registrationFee: 500,000원 (기본)
evictionCost: doc.eviction_risk.estimated_cost
repairCost: doc.condition.repair_estimate
assumedRightsAmount: doc.rights_analysis.assumed_amount  ← 미확인 시 undefined로 두어 경고 발생
unpaidManagementFee: doc.unpaid_management_fee (있을 경우)
agentCommissionRate: 0.005 (0.5%)
loanAmount: 사용자 지정 또는 0
loanAnnualRate: 사용자 지정 (loanAmount > 0이면 필수)
earlyRepaymentFeeRate: 0.01
transferTax: 사용자가 미지정 시 undefined → 경고 발생 (세무사 확인 권고)
```

#### 시나리오별 호출 예시

```
[보수 시나리오]
roi-calculator(auction, {
  bidPrice: 최저입찰가 × 1.00,
  expectedSalePrice: fair_value × 0.90,
  holdingPeriodMonths: 36,
  ...공통파라미터
})

[기준 시나리오]
roi-calculator(auction, {
  bidPrice: 최저입찰가 × 1.05,
  expectedSalePrice: fair_value × 1.00,
  holdingPeriodMonths: 24,
  ...공통파라미터
})

[공격 시나리오]
roi-calculator(auction, {
  bidPrice: 최저입찰가 × 1.12,
  expectedSalePrice: fair_value × 1.10,
  holdingPeriodMonths: 18,
  ...공통파라미터
})
```

#### 결과 비교 테이블 (roi-calculator 출력 집계)

```
| 시나리오 | 입찰가 | 예상매도가 | 낙찰가율 | 취득비용합계 | 순수익 | 연환산ROI | 경고 수 |
|---------|-------|----------|---------|------------|-------|---------|--------|
| 🔵 보수  |       |          |   %     |            |       |    %    |        |
| 🟡 기준  |       |          |   %     |            |       |    %    |        |
| 🔴 공격  |       |          |   %     |            |       |    %    |        |
```

---

### Step 5: 권고 입찰가 결정

기준 시나리오 연환산ROI 기준으로 판정한다.

| 기준 ROI | 판정 | 권고 입찰가 |
|---------|------|-----------|
| ≥ 15% | 적극 입찰 🟢 | 최저입찰가 × 1.05~1.12 |
| 10~15% | 소극 입찰 🟡 | 최저입찰가 × 1.00~1.05 |
| < 10% | 입찰 보류 🔴 | — |

최종 권고 입찰가 = min(공격 시나리오 bidPrice, fair_value × 0.85)

---

## 리스크 정량화

roi-calculator 경고 항목 외에 아래 리스크를 추가로 정량화한다.

| 리스크 | 확률 | 영향액 추정 |
|--------|------|------------|
| 명도 지연 (6개월 추가) | 15% | 보유비용 × 0.5년 |
| 숨은 권리관계 | 10% | 최저 500만 원 |
| 시장 하락 10% | 20% | expectedSalePrice × 10% |
| 수리비 초과 | 20% | repairCost × 50% |

예상 리스크 비용 = Σ(확률 × 영향액)

---

## 출력

`_workspace/03_bid_strategy_{cltrMngNo}.json`에 저장.
JSON 구조:

```json
{
  "cltrMngNo": "...",
  "fairValue": 0,
  "minBidPrice": 0,
  "scenarios": {
    "conservative": { /* roi-calculator AuctionROIOutput 전체 */ },
    "base":         { /* roi-calculator AuctionROIOutput 전체 */ },
    "aggressive":   { /* roi-calculator AuctionROIOutput 전체 */ }
  },
  "recommendation": {
    "verdict": "적극입찰 | 소극입찰 | 보류",
    "bidPrice": 0,
    "rationale": "..."
  },
  "risks": { /* 리스크 정량화 */ },
  "warnings": [ /* roi-calculator 3개 시나리오 경고 합집합 */ ]
}
```

상세 포맷은 `bid-strategist.md` 에이전트 정의 참조.
