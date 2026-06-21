# 갭투자 ROI 계산 공식 (상세)

출처: `lib/calc/gap.ts` (gonggong 저장소) — 2026-06 기준

---

## 상수 (constants)

| 상수 | 값 | 설명 |
|------|-----|------|
| DEFAULT_GAP_ACQUISITION_TAX_RATE | 0.011 (1.1%) | 1주택·6억 이하 기준. 6억 초과·다주택·조정지역은 최대 13.4% |
| DEFAULT_AGENT_COMMISSION_RATE_SALE | 0.005 (0.5%) | 매도 중개보수 |
| DEFAULT_REVERSE_JEONSE_DROP_RATE | 0.1 (10%) | 역전세 시뮬레이션 기본 하락률 |
| JEONSE_RATIO_WARNING_THRESHOLD | 80 (%) | 이 이상이면 역전세 고위험 경고 |
| JEONSE_RATIO_DANGER_THRESHOLD | 90 (%) | 이 이상이면 깡통전세 위험 경고 |

---

## 단계별 계산

### 1. 기본 지표
```
gap = purchasePrice - jeonseDeposit            ← 자기자본(투자금)
jeonseRatio = (jeonseDeposit / purchasePrice) × 100
capitalGain = expectedSalePrice - purchasePrice   ← 시세차익
```

### 2. 비용 계산
```
acquisitionTax = purchasePrice × acquisitionTaxRate

agentCommission = expectedSalePrice × agentCommissionRate

holdingTaxTotal = annualHoldingTax × (holdingPeriodMonths / 12)

# 단리 추정
loanInterest = (loanAmount > 0 && loanAnnualRate 있음)
             ? loanAmount × loanAnnualRate × (holdingPeriodMonths / 12)
             : 0

transferTaxApplied = transferTax ?? 0   ← undefined 시 경고

totalCost = acquisitionTax + agentCommission + holdingTaxTotal
          + loanInterest + transferTaxApplied
```

### 3. 수익 분석
```
investedCapital = gap + acquisitionTax + holdingTaxTotal   ← 투입자본(분모)

netProfit = capitalGain - totalCost

roe = (netProfit / investedCapital) × 100                     ← 자기자본수익률
annualizedRoe = roe × (12 / holdingPeriodMonths)              ← 연환산 ROE
leverageReturn = (capitalGain / gap) × (12 / holdingPeriodMonths) × 100  ← 참고용
```

### 4. 역전세 시뮬레이션
```
droppedDeposit = jeonseDeposit × (1 - reverseJeonseDropRate)
shortfall = jeonseDeposit - droppedDeposit                    ← 보증금 부족액
exceedsGap = shortfall > gap                                  ← 초기 갭 초과 여부

realNetProfit = netProfit - shortfall                         ← 역전세 반영 실질 순수익
realRoe = (realNetProfit / investedCapital) × 100             ← 역전세 반영 실질 ROE
```

---

## 입력 검증 규칙

| 조건 | 처리 |
|------|------|
| purchasePrice ≤ 0 | Error |
| jeonseDeposit < 0 | Error |
| jeonseDeposit ≥ purchasePrice | Error (갭 ≤ 0, 투자 성립 불가) |
| expectedSalePrice < 0 | Error |
| holdingPeriodMonths < 1 | Error |
| acquisitionTaxRate ∉ [0,1] | Error |
| annualHoldingTax < 0 | Error |
| agentCommissionRate ∉ [0,1] | Error |
| loanAmount < 0 | Error |
| loanAnnualRate ∉ [0,1] | Error |
| transferTax < 0 | Error |
| reverseJeonseDropRate ∉ [0,1] | Error |

---

## 예시

매매가 4.09억, 전세 3.18억, 예상매도가 4.3억, 24개월, 취득세율 1.1%:

```
갭 = 4.09억 - 3.18억 = 0.91억 = 9,100만 원
전세가율 = 3.18 / 4.09 × 100 = 77.7%  ← 경고 없음

취득세 = 4.09억 × 0.011 = 450만 원
중개수수료 = 4.3억 × 0.005 = 215만 원
보유세합계 = 0 (미입력)
총비용 = 450 + 215 = 665만 원 (양도세 미입력 시 경고)

투입자본 = 9,100 + 450 = 9,550만 원
시세차익 = 4.3 - 4.09 = 0.21억 = 2,100만 원
순수익 = 2,100 - 665 = 1,435만 원

ROE = 1,435 / 9,550 × 100 = 15.0%
연환산ROE = 15.0 × (12/24) = 7.5%
레버리지수익률 = (2,100 / 9,100) × (12/24) × 100 = 11.5%

역전세 시뮬레이션 (10% 하락):
  하락후전세 = 3.18 × 0.9 = 2.862억
  부족액 = 3.18 - 2.862 = 0.318억 = 3,180만 원
  갭(9,100) > 부족액(3,180) → exceedsGap = false
  실질순수익 = 1,435 - 3,180 = -1,745만 원  ← 역전세 시 손실
  실질ROE = -1,745 / 9,550 × 100 = -18.3%
```
