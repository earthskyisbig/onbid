---
name: bid-analysis
description: 공매 물건의 입찰가를 산정하고 수익성을 분석하는 스킬. 감정평가 대비 할인율 계산, 취득비용 산정, 3가지 시나리오 수익성 분석, 리스크 정량화, 최적 입찰가 권고. "입찰가 산정", "수익성 분석", "ROI 계산", "얼마에 입찰", "투자 수익", "시나리오 분석" 등의 요청 시 반드시 이 스킬을 사용할 것.
---

# 입찰가 산정·수익성 분석 스킬

## 분석 절차

### Step 1: 입력 데이터 로드
```python
import json

def load_analysis_data(cltr_mng_no, workspace='_workspace'):
    doc = json.load(open(f'{workspace}/02_doc_analysis_{cltr_mng_no}.json'))
    loc = json.load(open(f'{workspace}/02_location_analysis_{cltr_mng_no}.json'))
    search = json.load(open(f'{workspace}/01_search_results.json'))
    property_data = next(p for p in search['properties'] if p.get('cltrMngNo') == cltr_mng_no or p.get('pbancMngNo'))
    return doc, loc, property_data
```

### Step 2: 적정가치 산정
```python
def calculate_fair_value(appraisal_amount, loc_score, dev_bonus):
    """
    appraisal_amount: 감정평가금액
    loc_score: 입지종합점수 (1-5)
    dev_bonus: 개발호재 가중치 (0.0 ~ 0.3)
    """
    base = appraisal_amount
    loc_factor = 0.8 + (loc_score / 5 * 0.4)  # 0.8~1.2
    fair_value = base * loc_factor * (1 + dev_bonus)
    return fair_value
```

### Step 3: 취득 비용 계산
```python
def calc_acquisition_costs(bid_price, property_type='일반부동산'):
    rates = {
        '일반부동산': {'취득세': 0.04, '농어촌특별세': 0.002, '지방교육세': 0.004},
        '농지': {'취득세': 0.03, '농어촌특별세': 0.002, '지방교육세': 0.003},
        '주택1채': {'취득세': 0.01, '농어촌특별세': 0.002, '지방교육세': 0.001},
    }
    rate = rates.get(property_type, rates['일반부동산'])
    total_rate = sum(rate.values())
    return {
        '취득세': bid_price * rate['취득세'],
        '농어촌특별세': bid_price * rate['농어촌특별세'],
        '지방교육세': bid_price * rate['지방교육세'],
        '등기비용': 500000,
        '법무사수수료': 300000,
        'total': bid_price * total_rate + 800000
    }
```

### Step 4: 시나리오별 수익성
```python
def calc_scenarios(bid_price, acq_costs, fair_value):
    total_investment = bid_price + acq_costs['total']
    scenarios = {
        '낙관': {'배율': 1.25, '보유개월': 18},
        '기준': {'배율': 1.05, '보유개월': 24},
        '보수': {'배율': 0.90, '보유개월': 36},
    }
    results = {}
    for name, s in scenarios.items():
        sale_price = fair_value * s['배율']
        holding_costs = total_investment * 0.005 * (s['보유개월'] / 12)
        양도세 = max(0, (sale_price - total_investment) * 0.22)  # 기본세율
        net_profit = sale_price - total_investment - holding_costs - 양도세
        roi = net_profit / total_investment * 100
        results[name] = {
            'sale_price': round(sale_price),
            'holding_costs': round(holding_costs),
            '양도소득세': round(양도세),
            'net_profit': round(net_profit),
            'roi_pct': round(roi, 1)
        }
    return results
```

### Step 5: 권고 입찰가 결정
- 기준 시나리오 ROI ≥ 15%: 최저입찰가 + α 에서 적극 입찰
- 기준 시나리오 ROI 10~15%: 최저입찰가 수준에서 소극 입찰
- 기준 시나리오 ROI < 10%: 입찰 보류 권고

입찰가 = min(권고최대값, 적정가치 × 0.80)

## 리스크 정량화
| 리스크 | 확률 | 영향액 추정 |
|--------|------|------------|
| 명도 지연 (6개월) | 15% | 보유비용 + 법적비용 |
| 숨은 권리관계 | 10% | 최저 500만원 |
| 시장 하락 10% | 20% | 매각가 × 10% |
| 공사 필요 | 20% | 건물 현상에 따라 |

예상 리스크 비용 = Σ(확률 × 영향액)

## 출력
`_workspace/03_bid_strategy_{cltrMngNo}.json`에 저장
상세 포맷은 `bid-strategist.md` 에이전트 정의 참조
