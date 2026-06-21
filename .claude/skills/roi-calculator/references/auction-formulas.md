# 경매/공매 ROI 계산 공식 (상세)

출처: `lib/calc/auction.ts` (gonggong 저장소) — 2026-06 기준

---

## 상수 (constants)

| 상수 | 값 | 설명 |
|------|-----|------|
| DEFAULT_ACQUISITION_TAX_RATE | 0.046 (4.6%) | 취득세+지방교육세+농특세 추정 합산. 실제는 주택수·가격·지역 따라 1~12% |
| DEFAULT_AGENT_COMMISSION_RATE_SALE | 0.005 (0.5%) | 매도 중개보수 상한 보수적 추정. 공인중개사법 시행규칙 별표 1 |
| DEFAULT_EARLY_REPAYMENT_FEE_RATE | 0.01 (1%) | 중도상환수수료 기본값. 실제 대출계약서 확인 필요 |

---

## 단계별 계산

### 1. 낙찰가율
```
bidToAppraisalRatio = (bidPrice / appraisalValue) × 100
```
- bidPrice > appraisalValue 이면 경고 (계산은 계속)

### 2. 취득비용 합계 (totalAcquisitionCost)
```
acquisitionTax = bidPrice × acquisitionTaxRate

totalAcquisitionCost = bidPrice
                     + acquisitionTax
                     + legalFee
                     + registrationFee
                     + evictionCost
                     + repairCost
                     + interiorCost
                     + assumedRightsAmount  ← undefined 시 0, 경고 추가
                     + unpaidManagementFee
```

### 3. 매도비용 합계 (totalExitCost)
```
agentCommission = expectedSalePrice × agentCommissionRate

exitTax = (ownerType === 'individual') ? transferTax ?? 0
                                       : businessTax ?? 0

totalExitCost = agentCommission + exitTax
```

### 4. 금융비용 합계 (totalFinanceCost)
```
# 단리 추정
loanInterest = (loanAmount > 0 && loanAnnualRate 있음)
             ? loanAmount × loanAnnualRate × (holdingPeriodMonths / 12)
             : 0

earlyRepaymentFee = (loanAmount > 0)
                  ? loanAmount × earlyRepaymentFeeRate
                  : 0

totalFinanceCost = loanInterest + earlyRepaymentFee
```

### 5. 수익 분석
```
netProfit = expectedSalePrice - totalAcquisitionCost - totalExitCost - totalFinanceCost

annualizedROI = (netProfit / totalAcquisitionCost) × (12 / holdingPeriodMonths) × 100
```
- 분모: 취득비용합계 (입찰가 + 모든 취득 단계 비용)
- netProfit < 0 이면 경고 추가

---

## 입력 검증 규칙

| 조건 | 처리 |
|------|------|
| appraisalValue ≤ 0 | Error |
| bidPrice ≤ 0 | Error |
| holdingPeriodMonths < 1 | Error |
| 비용 항목 < 0 | Error |
| acquisitionTaxRate ∉ [0,1] | Error |
| agentCommissionRate ∉ [0,1] | Error |
| loanAmount < 0 | Error |
| loanAnnualRate ∉ [0,1] | Error |
| earlyRepaymentFeeRate ∉ [0,1] | Error |
| transferTax < 0 | Error |
| businessTax < 0 | Error |
| assumedRightsAmount < 0 | Error |

---

## 예시

입찰가 3.825억, 감정가 4.25억, 예상매도가 4.09억, 개인, 6개월 보유, 취득세율 4.6%:

```
낙찰가율 = 3.825 / 4.25 × 100 = 90.0%

취득세 = 3.825억 × 0.046 = 0.1759억 ≈ 1,759만 원
취득비용합계 = 3.825 + 0.1759 = 4.0009억 (기타 비용 0 가정)

중개수수료 = 4.09억 × 0.005 = 205만 원
매도비용합계 = 205만 원 (양도세 미입력 시 경고)

금융비용합계 = 0 (대출 없음)

순수익 = 4.09억 - 4.0009억 - 0.0205억 = 0.0686억 ≈ 686만 원
연환산ROI = (686만 / 4.0009억) × (12/6) × 100 ≈ 3.4%
```
