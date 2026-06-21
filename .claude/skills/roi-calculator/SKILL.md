# roi-calculator

부동산 투자 ROI 계산 스킬. 경매/공매와 갭투자 두 가지 모드를 지원한다.
계산 로직은 `references/auction-formulas.md`, `references/gap-formulas.md`를 따른다.

---

## 트리거

다음 상황에서 이 스킬을 호출한다:
- "ROI 계산해줘", "수익률 계산", "입찰 수익성 분석"
- `bid-analysis` 스킬 내에서 수익률 산정 단계
- 온비드 물건 분석 파이프라인의 **입찰가 산정** 단계

---

## 모드 선택

| 모드 | 설명 | 사용 시점 |
|------|------|---------|
| `auction` | 경매/공매 낙찰 후 매도 수익률 | 온비드 공매 물건 분석 (기본) |
| `gap` | 갭투자 자기자본수익률 | 갭 매수 시나리오 분석 |

---

## STEP 1: 입력 수집

### 경매/공매 모드 (auction)

**필수 입력**
| 항목 | 변수명 | 단위 | 비고 |
|------|--------|------|------|
| 투자 주체 | ownerType | individual / business | 개인=양도세, 사업자=사업소득세 |
| 감정가 | appraisalValue | 원 | > 0 |
| 입찰(예정)가 | bidPrice | 원 | > 0 |
| 예상 보유기간 | holdingPeriodMonths | 월 | ≥ 1 |
| 예상 매도가 | expectedSalePrice | 원 | ≥ 0 |

**선택 입력 (미입력 시 기본값 또는 경고)**
| 항목 | 변수명 | 기본값 | 비고 |
|------|--------|--------|------|
| 취득세율 | acquisitionTaxRate | 4.6% | 주택수·가격·지역 따라 상이 |
| 법무비용 | legalFee | 0 | 법무사 보수+등기수수료 |
| 등록세/등기비용 | registrationFee | 0 | 국민주택채권+법원수수료 |
| 명도비용 | evictionCost | 0 | |
| 수리비 | repairCost | 0 | |
| 인테리어비용 | interiorCost | 0 | |
| 권리분석 인수금액 | assumedRightsAmount | ⚠️미반영경고 | undefined 시 경고 강제 |
| 체납관리비 | unpaidManagementFee | 0 | |
| 중개수수료율(매도) | agentCommissionRate | 0.5% | |
| 대출금액 | loanAmount | 0 | |
| 대출 연이율 | loanAnnualRate | ⚠️미반영경고 | loanAmount > 0이면 필수 |
| 중도상환수수료율 | earlyRepaymentFeeRate | 1% | |
| 양도세(개인) | transferTax | ⚠️미반영경고 | undefined 시 경고 |
| 사업소득세(사업자) | businessTax | ⚠️미반영경고 | undefined 시 경고 |

### 갭투자 모드 (gap)

**필수 입력**
| 항목 | 변수명 | 단위 | 비고 |
|------|--------|------|------|
| 매매가 | purchasePrice | 원 | > 0 |
| 전세보증금 | jeonseDeposit | 원 | 매매가 미만이어야 함 |
| 예상 매도가 | expectedSalePrice | 원 | ≥ 0 |
| 예상 보유기간 | holdingPeriodMonths | 월 | ≥ 1 |

**선택 입력**
| 항목 | 변수명 | 기본값 |
|------|--------|--------|
| 취득세율 | acquisitionTaxRate | 1.1% |
| 연간 보유세 | annualHoldingTax | 0 |
| 중개수수료율(매도) | agentCommissionRate | 0.5% |
| 대출금액 | loanAmount | 0 |
| 대출 연이율 | loanAnnualRate | ⚠️미반영경고 |
| 양도세 | transferTax | ⚠️미반영경고 |
| 역전세 하락률 | reverseJeonseDropRate | 10% |

---

## STEP 2: 입력 검증

**공통 검증 (위반 시 Error, 계산 중단)**
- 감정가/매매가 > 0
- 입찰가/매매가 > 0
- 보유기간 ≥ 1 (월)
- 비용 항목 ≥ 0 (음수 불가)
- 세율·수수료율 ∈ [0, 1]

**경매 전용**
- 입찰가 > 감정가 → 경고 추가 (계산 계속)
- assumedRightsAmount 미입력 → 경고 강제

**갭투자 전용**
- 전세보증금 ≥ 매매가 → Error (갭 ≤ 0, 투자 성립 불가)

---

## STEP 3: 계산

자세한 공식은 `references/auction-formulas.md`, `references/gap-formulas.md` 참조.

### 경매 핵심 산식
```
낙찰가율 = bidPrice / appraisalValue × 100

취득비용합계 = bidPrice
             + bidPrice × acquisitionTaxRate    ← 취득세
             + legalFee
             + registrationFee
             + evictionCost + repairCost + interiorCost
             + assumedRightsAmount + unpaidManagementFee

매도비용합계 = expectedSalePrice × agentCommissionRate   ← 중개수수료
             + (transferTax | businessTax)               ← 세금

금융비용합계 = loanAmount × loanAnnualRate × (holdingPeriodMonths / 12)  ← 이자(단리)
             + loanAmount × earlyRepaymentFeeRate                         ← 중도상환수수료

순수익 = expectedSalePrice - 취득비용합계 - 매도비용합계 - 금융비용합계

연환산ROI = (순수익 / 취득비용합계) × (12 / holdingPeriodMonths) × 100
```

### 갭투자 핵심 산식
```
갭(자기자본) = purchasePrice - jeonseDeposit
전세가율 = jeonseDeposit / purchasePrice × 100
시세차익 = expectedSalePrice - purchasePrice

취득세 = purchasePrice × acquisitionTaxRate
중개수수료 = expectedSalePrice × agentCommissionRate
보유세합계 = annualHoldingTax × (holdingPeriodMonths / 12)
대출이자 = loanAmount × loanAnnualRate × (holdingPeriodMonths / 12)   ← 단리
총비용 = 취득세 + 중개수수료 + 보유세합계 + 대출이자 + transferTax

투입자본 = 갭 + 취득세 + 보유세합계
순수익 = 시세차익 - 총비용
ROE = 순수익 / 투입자본 × 100
연환산ROE = ROE × (12 / holdingPeriodMonths)
레버리지수익률 = (시세차익 / 갭) × (12 / holdingPeriodMonths) × 100   ← 참고지표

역전세 시뮬레이션:
  하락후전세 = jeonseDeposit × (1 - reverseJeonseDropRate)
  보증금부족액 = jeonseDeposit - 하락후전세
  역전세실질순수익 = 순수익 - 보증금부족액
  역전세실질ROE = 역전세실질순수익 / 투입자본 × 100
```

---

## STEP 4: 경고 생성

**경매 경고 조건**
| 조건 | 경고 메시지 |
|------|-----------|
| assumedRightsAmount 미입력 | 권리분석 미반영 — 인수금액 미입력 시 실제 비용이 증가할 수 있습니다 |
| loanAmount > 0, loanAnnualRate 미입력 | 대출 연이율 미입력 — 이자비용이 수익률에 반영되지 않았습니다 |
| ownerType=individual, transferTax 미입력 | 양도세 미반영 — 보유기간·주택수·지역에 따라 세후 수익이 크게 달라집니다 |
| ownerType=business, businessTax 미입력 | 사업소득세 미반영 — 실제 과세소득 기준 세무사 확인이 필요합니다 |
| bidPrice > appraisalValue | 입찰가가 감정가를 초과합니다 (낙찰가율 100% 초과) |
| netProfit < 0 | 예상 순수익이 마이너스입니다 — 입찰가·비용을 재검토하세요 |

**갭투자 경고 조건**
| 조건 | 경고 메시지 |
|------|-----------|
| 전세가율 ≥ 90% | 전세가율 90% 이상 — 깡통전세 위험. 시세 하락 시 보증금 미반환 가능성이 큽니다 |
| 전세가율 ≥ 80% | 전세가율 80% 이상 — 역전세 고위험. 전세금반환보증(HUG/SGI) 가입 여부를 확인하세요 |
| loanAmount > 0, loanAnnualRate 미입력 | 대출 연이율 미입력 — 이자비용이 수익률에 반영되지 않았습니다 |
| transferTax 미입력 | 양도세 미반영 — 보유기간·주택수·조정대상지역에 따라 세후 수익이 크게 달라집니다 |
| 보증금부족액 > 갭 | 역전세 발생 시 필요한 추가 현금이 초기 투자금(갭)을 초과합니다 |
| netProfit < 0 | 예상 순수익이 마이너스입니다 — 매도가·비용을 재검토하세요 |

---

## STEP 5: 출력 포맷

계산 결과는 다음 구조로 출력한다.

### 경매 ROI 결과

```
## 경매/공매 ROI 분석 결과

### 기본 정보
- 투자 주체: 개인 / 매매사업자
- 감정가: X.XX억 원
- 입찰가: X.XX억 원 (낙찰가율 XX.X%)
- 예상 매도가: X.XX억 원
- 보유기간: XX개월

### 비용 상세
| 항목 | 금액 |
|------|------|
| 취득세 | X,XXX만 원 |
| 법무비용 | X,XXX만 원 |
| 등록세/등기비용 | X,XXX만 원 |
| 명도비용 | X,XXX만 원 |
| 수리비+인테리어 | X,XXX만 원 |
| 권리분석 인수금액 | X,XXX만 원 |
| 체납관리비 | X,XXX만 원 |
| **취득비용 합계** | **X.XX억 원** |
| 매도 중개수수료 | X,XXX만 원 |
| 양도세/사업소득세 | X,XXX만 원 |
| **매도비용 합계** | **X,XXX만 원** |
| 대출이자 | X,XXX만 원 |
| 중도상환수수료 | X,XXX만 원 |
| **금융비용 합계** | **X,XXX만 원** |

### 수익 분석
- 세후 순수익: **X,XXX만 원**
- 연환산 ROI: **X.X%**

### ⚠️ 경고
- (해당 경고 목록)

> (고지 문구)
```

### 갭투자 ROI 결과

```
## 갭투자 ROI 분석 결과

### 기본 정보
- 매매가: X.XX억 원
- 전세보증금: X.XX억 원 (전세가율 XX.X%)
- 갭(자기자본): X,XXX만 원
- 예상 매도가: X.XX억 원
- 보유기간: XX개월

### 비용 상세
| 항목 | 금액 |
|------|------|
| 취득세 | X,XXX만 원 |
| 매도 중개수수료 | X,XXX만 원 |
| 보유세 합계 | X,XXX만 원 |
| 대출이자 | X,XXX만 원 |
| 양도세 | X,XXX만 원 |
| **총비용** | **X,XXX만 원** |

### 수익 분석
- 시세차익: X,XXX만 원
- 순수익: **X,XXX만 원**
- 투입자본: X,XXX만 원
- ROE: **X.X%**
- 연환산 ROE: **X.X%**
- 레버리지 수익률: X.X% (참고)

### 역전세 시뮬레이션 (전세가 X% 하락 가정)
- 하락 후 전세: X,XXX만 원
- 보증금 부족액: X,XXX만 원
- 역전세 반영 실질 순수익: X,XXX만 원
- 역전세 반영 실질 ROE: X.X%

### ⚠️ 경고
- (해당 경고 목록)

> (고지 문구)
```

---

## 온비드 파이프라인 통합

`bid-analysis` 스킬에서 이 스킬을 호출할 때:
1. 입찰가 시나리오별(보수/적정/공격) `bidPrice`를 달리 설정해 3회 실행
2. `assumedRightsAmount`는 `document-analysis` 결과에서 가져온다
3. `expectedSalePrice`는 `molit-market-data` 조회 결과(매매 시세 평균)를 사용
4. 결과를 `_workspace/03_bid_strategy_[물건번호].json`에 포함

---

## 고지 문구

**개인**
> 본 계산 결과는 참고용 추정치입니다. 양도세는 보유기간·주택수·조정대상지역 여부에 따라 크게 달라지므로 반드시 세무사 확인이 필요합니다. 취득세는 주택수·가격구간·지역에 따라 1~12%로 상이하며, 대출 이자 등 보유비용은 미반영되어 있습니다.

**매매사업자**
> 본 계산 결과는 참고용 추정치입니다. 매매사업자는 양도세 대신 사업소득(종합소득세)이 적용되며, 부가가치세(주택 외 부동산), 의무매입 국민주택채권 등 추가 비용이 발생할 수 있습니다. 실제 세금·비용은 세무사·법무사 확인이 필요합니다.

**갭투자**
> 본 계산 결과는 참고용 추정치입니다. 양도세는 보유기간·주택수·조정대상지역 여부에 따라 크게 달라지므로 반드시 세무사 확인이 필요합니다. 취득세는 주택수·가격구간·지역에 따라 1~13.4%로 상이하며, 역전세 시뮬레이션은 가정 하락률에 따른 보수적 추정으로 실제 전세 시세와 다를 수 있습니다.
