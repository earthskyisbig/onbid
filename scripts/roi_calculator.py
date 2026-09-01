#!/usr/bin/env python3
"""
roi-calculator 스킬의 결정론적 구현.

공식 출처: .claude/skills/roi-calculator/references/auction-formulas.md, gap-formulas.md
LLM이 암산으로 ROI를 만들지 않도록, bid-analysis 단계는 반드시 이 스크립트를 호출한다.

서브커맨드:
    auction    경매/공매 낙찰 후 매도 ROI (단일 케이스)
    gap        갭투자 ROE (단일 케이스)
    scenarios  bid-analysis 스킬의 보수/기준/공격 3시나리오 + 권고 판정을 한 번에 산출
               → _workspace/03_bid_strategy_{cltrMngNo}.json 골격 생성

사용 예:
    python3 scripts/roi_calculator.py auction \
        --appraisal 425000000 --bid 382500000 --sale 409000000 --months 6

    python3 scripts/roi_calculator.py gap \
        --purchase 409000000 --jeonse 318000000 --sale 430000000 --months 24

    python3 scripts/roi_calculator.py scenarios \
        --cltr-mng-no 2026-16156-004 \
        --appraisal 250000000 --min-bid 200000000 --fair-value 255000000 \
        --acq-tax-rate 0.011 --legal-fee 300000 --registration-fee 500000 \
        --eviction-cost 2000000 --repair-cost 3000000 --assumed-rights 0 \
        --output _workspace/03_bid_strategy_2026-16156-004.json

    # 파라미터가 많으면 JSON 파일로:
    python3 scripts/roi_calculator.py scenarios --json-in params.json --output ...

모든 금액은 원(₩) 단위, 비율은 소수(0.046 = 4.6%).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import format_price  # noqa: E402

# ─────────────────────────── 상수 ───────────────────────────
DEFAULT_ACQUISITION_TAX_RATE = 0.046       # 일반 부동산 취득세+지방교육세+농특세
DEFAULT_GAP_ACQUISITION_TAX_RATE = 0.011   # 1주택·6억 이하
DEFAULT_AGENT_COMMISSION_RATE = 0.005
DEFAULT_EARLY_REPAYMENT_FEE_RATE = 0.01
DEFAULT_REVERSE_JEONSE_DROP_RATE = 0.10
JEONSE_RATIO_WARNING = 80.0
JEONSE_RATIO_DANGER = 90.0

# bid-analysis 스킬 시나리오 정의 (bidMultiplier, saleMultiplier, holdingMonths)
SCENARIOS = {
    'conservative': {'label': '보수', 'bid': 1.00, 'sale': 0.90, 'months': 36},
    'base':         {'label': '기준', 'bid': 1.05, 'sale': 1.00, 'months': 24},
    'aggressive':   {'label': '공격', 'bid': 1.12, 'sale': 1.10, 'months': 18},
}
VERDICT_ACTIVE = 15.0   # 기준 시나리오 연환산 ROI ≥ 15% → 적극 입찰
VERDICT_PASSIVE = 10.0  # 10~15% → 소극 입찰, 미만 → 보류
FAIR_VALUE_CAP = 0.85   # 최종 권고 입찰가 상한 = fair_value × 0.85

DISCLAIMER = {
    'individual': ("본 계산 결과는 참고용 추정치입니다. 양도세는 보유기간·주택수·조정대상지역 여부에 따라 "
                   "크게 달라지므로 반드시 세무사 확인이 필요합니다. 취득세는 주택수·가격구간·지역에 따라 "
                   "1~12%로 상이하며, 대출 이자 등 보유비용은 입력값 범위에서만 반영되어 있습니다."),
    'business':   ("본 계산 결과는 참고용 추정치입니다. 매매사업자는 양도세 대신 사업소득(종합소득세)이 "
                   "적용되며, 부가가치세(주택 외 부동산), 의무매입 국민주택채권 등 추가 비용이 발생할 수 "
                   "있습니다. 실제 세금·비용은 세무사·법무사 확인이 필요합니다."),
    'gap':        ("본 계산 결과는 참고용 추정치입니다. 양도세는 보유기간·주택수·조정대상지역 여부에 따라 "
                   "크게 달라지므로 반드시 세무사 확인이 필요합니다. 취득세는 주택수·가격구간·지역에 따라 "
                   "1~13.4%로 상이하며, 역전세 시뮬레이션은 가정 하락률에 따른 보수적 추정입니다."),
}


# ─────────────────────────── 취득세율 (지방세법 §11·§13의2, 2026-09 기준) ───────────────────────────
PROPERTY_KINDS = ('house', 'officetel', 'commercial', 'land', 'building', 'farmland')


def acquisition_tax_rate(kind: str = 'house', price: float | None = None, area_sqm: float | None = None,
                         house_count: int = 1, adjusted_area: bool = False) -> dict:
    """
    취득세 + 지방교육세 + 농어촌특별세 합산 세율(소수)을 돌려준다. 경매·공매 낙찰은 유상취득으로 본다.
    kind: house(주택) / officetel(오피스텔·업무용) / commercial(상가) / land(토지) / building(비주택 건물) / farmland(농지)
    house_count: 취득 후 보유 주택 수 (이번 물건 포함). adjusted_area: 조정대상지역 여부.
    반환: {'rate', 'components': {acquisition, education, special}, 'basis', 'notes': [...]}
    ※ 감면(생애최초·신축 등)·일시적 2주택 예외는 반영하지 않는다 — notes 로 안내.
    """
    notes = []
    if kind == 'house':
        if price is None or price <= 0:
            raise ROIInputError("주택 취득세율 계산에는 취득가액(price)이 필요합니다")
        large = bool(area_sqm and area_sqm > 85)
        heavy12 = (adjusted_area and house_count >= 3) or (not adjusted_area and house_count >= 4)
        heavy8 = (adjusted_area and house_count == 2) or (not adjusted_area and house_count == 3)
        if heavy12:
            acq, edu, spc = 0.12, 0.004, (0.01 if large else 0.0)
            basis = f"{'조정지역 3주택↑' if adjusted_area else '비조정 4주택↑'} 중과 12%"
            notes.append("다주택 중과세율 적용 — 일시적 2주택·상속·감면 예외는 미반영. 세무사 확인 필수")
        elif heavy8:
            acq, edu, spc = 0.08, 0.004, (0.006 if large else 0.0)
            basis = f"{'조정지역 2주택' if adjusted_area else '비조정 3주택'} 중과 8%"
            notes.append("다주택 중과세율 적용 — 일시적 2주택(종전주택 3년 내 처분) 해당 시 일반세율. 세무사 확인 필수")
        else:
            if price <= 600_000_000:
                acq = 0.01
                basis = "주택 6억 이하 1%"
            elif price <= 900_000_000:
                acq = round((price * 2 / 300_000_000 - 3) / 100, 4)   # (가액×2/3억 − 3)%, 소수 둘째자리 반올림
                basis = f"주택 6~9억 누진 {acq*100:.2f}%"
            else:
                acq = 0.03
                basis = "주택 9억 초과 3%"
            edu = round(acq / 10, 5)
            spc = 0.002 if large else 0.0
            if house_count == 2 and not adjusted_area:
                notes.append("비조정지역 2주택은 일반세율 (조정지역이면 8% 중과)")
        if large:
            notes.append("전용 85㎡ 초과 — 농어촌특별세 가산")
        else:
            notes.append("전용 85㎡ 이하 — 농어촌특별세 비과세")
    elif kind in ('officetel', 'commercial', 'land', 'building'):
        acq, edu, spc = 0.04, 0.004, 0.002
        basis = "비주택 부동산 일반 4% (+교육세 0.4% +농특세 0.2%)"
        if kind == 'officetel':
            notes.append("오피스텔은 취득 시 비주택 4.6%. 주거용 사용 중이면 보유 주택 수에는 산입될 수 있음")
    elif kind == 'farmland':
        acq, edu, spc = 0.03, 0.002, 0.002
        basis = "농지 3% (+교육세 0.2% +농특세 0.2%)"
        notes.append("2년 이상 자경 농민이 취득하면 1.5% 감면세율 — 요건 확인 필요")
    else:
        raise ROIInputError(f"kind 는 {PROPERTY_KINDS} 중 하나여야 합니다: {kind!r}")
    rate = round(acq + edu + spc, 5)
    return {'rate': rate, 'components': {'acquisition': acq, 'education': edu, 'special': spc},
            'basis': basis + f" → 합계 {rate*100:.2f}%", 'kind': kind, 'price': price, 'area_sqm': area_sqm,
            'house_count': house_count, 'adjusted_area': adjusted_area, 'notes': notes}


class ROIInputError(ValueError):
    """입력 검증 실패 (계산 중단)."""


# ─────────────────────────── 검증 헬퍼 ───────────────────────────
def _num(inputs: dict, key: str, default=None):
    v = inputs.get(key, default)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ROIInputError(f"{key} 는 숫자여야 합니다: {v!r}")


def _require_positive(name, v):
    if v is None or v <= 0:
        raise ROIInputError(f"{name} 은(는) 0보다 커야 합니다 (입력: {v})")


def _require_nonneg(name, v):
    if v is not None and v < 0:
        raise ROIInputError(f"{name} 은(는) 음수일 수 없습니다 (입력: {v})")


def _require_rate(name, v):
    if v is not None and not (0.0 <= v <= 1.0):
        raise ROIInputError(f"{name} 은(는) 0~1 사이의 소수여야 합니다 (입력: {v}). 4.6% → 0.046")


# ─────────────────────────── 경매/공매 ───────────────────────────
def calc_auction(inputs: dict) -> dict:
    """
    경매/공매 ROI. inputs 키는 roi-calculator SKILL.md 변수명(camelCase)을 그대로 쓴다.
    필수: appraisalValue, bidPrice, holdingPeriodMonths, expectedSalePrice
    """
    owner = (inputs.get('ownerType') or 'individual').lower()
    if owner not in ('individual', 'business'):
        raise ROIInputError("ownerType 은 individual 또는 business 여야 합니다")

    appraisal = _num(inputs, 'appraisalValue')
    bid = _num(inputs, 'bidPrice')
    months = _num(inputs, 'holdingPeriodMonths')
    sale = _num(inputs, 'expectedSalePrice')
    _require_positive('appraisalValue', appraisal)
    _require_positive('bidPrice', bid)
    if months is None or months < 1:
        raise ROIInputError(f"holdingPeriodMonths 는 1 이상이어야 합니다 (입력: {months})")
    if sale is None or sale < 0:
        raise ROIInputError(f"expectedSalePrice 는 0 이상이어야 합니다 (입력: {sale})")

    tax_basis = None
    acq_rate = _num(inputs, 'acquisitionTaxRate')
    if acq_rate is None and inputs.get('propertyKind'):
        tax_basis = acquisition_tax_rate(inputs['propertyKind'], price=bid,
                                         area_sqm=_num(inputs, 'areaSqm'),
                                         house_count=int(inputs.get('houseCount') or 1),
                                         adjusted_area=bool(inputs.get('adjustedArea')))
        acq_rate = tax_basis['rate']
    elif acq_rate is None:
        acq_rate = DEFAULT_ACQUISITION_TAX_RATE
    legal = _num(inputs, 'legalFee', 0) or 0
    regist = _num(inputs, 'registrationFee', 0) or 0
    evict = _num(inputs, 'evictionCost', 0) or 0
    repair = _num(inputs, 'repairCost', 0) or 0
    interior = _num(inputs, 'interiorCost', 0) or 0
    assumed = _num(inputs, 'assumedRightsAmount')          # None 허용 → 경고
    unpaid = _num(inputs, 'unpaidManagementFee', 0) or 0
    comm_rate = _num(inputs, 'agentCommissionRate', DEFAULT_AGENT_COMMISSION_RATE)
    loan = _num(inputs, 'loanAmount', 0) or 0
    loan_rate = _num(inputs, 'loanAnnualRate')              # None 허용 → 경고
    early_rate = _num(inputs, 'earlyRepaymentFeeRate', DEFAULT_EARLY_REPAYMENT_FEE_RATE)
    transfer_tax = _num(inputs, 'transferTax')
    business_tax = _num(inputs, 'businessTax')

    for name, v in [('legalFee', legal), ('registrationFee', regist), ('evictionCost', evict),
                    ('repairCost', repair), ('interiorCost', interior),
                    ('assumedRightsAmount', assumed), ('unpaidManagementFee', unpaid),
                    ('loanAmount', loan), ('transferTax', transfer_tax), ('businessTax', business_tax)]:
        _require_nonneg(name, v)
    for name, v in [('acquisitionTaxRate', acq_rate), ('agentCommissionRate', comm_rate),
                    ('loanAnnualRate', loan_rate), ('earlyRepaymentFeeRate', early_rate)]:
        _require_rate(name, v)

    warnings: list[str] = []

    # 1. 낙찰가율
    ratio = bid / appraisal * 100
    if bid > appraisal:
        warnings.append("입찰가가 감정가를 초과합니다 (낙찰가율 100% 초과)")

    # 2. 취득비용
    acq_tax = bid * acq_rate
    if assumed is None:
        warnings.append("권리분석 미반영 — 인수금액(assumedRightsAmount) 미입력 시 실제 비용이 증가할 수 있습니다")
        assumed_applied = 0.0
    else:
        assumed_applied = assumed
    total_acq = bid + acq_tax + legal + regist + evict + repair + interior + assumed_applied + unpaid

    # 3. 매도비용
    commission = sale * comm_rate
    if owner == 'individual':
        if transfer_tax is None:
            warnings.append("양도세 미반영 — 보유기간·주택수·지역에 따라 세후 수익이 크게 달라집니다")
        exit_tax = transfer_tax or 0.0
    else:
        if business_tax is None:
            warnings.append("사업소득세 미반영 — 실제 과세소득 기준 세무사 확인이 필요합니다")
        exit_tax = business_tax or 0.0
    total_exit = commission + exit_tax

    # 4. 금융비용 (단리)
    if loan > 0 and loan_rate is None:
        warnings.append("대출 연이율 미입력 — 이자비용이 수익률에 반영되지 않았습니다")
    interest = loan * loan_rate * (months / 12) if (loan > 0 and loan_rate is not None) else 0.0
    early_fee = loan * early_rate if loan > 0 else 0.0
    total_fin = interest + early_fee

    # 5. 수익
    net = sale - total_acq - total_exit - total_fin
    simple_roi = net / total_acq * 100
    annual_roi = simple_roi * (12 / months)
    if net < 0:
        warnings.append("예상 순수익이 마이너스입니다 — 입찰가·비용을 재검토하세요")

    return {
        'mode': 'auction',
        'ownerType': owner,
        'inputs': {
            'appraisalValue': appraisal, 'bidPrice': bid, 'expectedSalePrice': sale,
            'holdingPeriodMonths': months, 'acquisitionTaxRate': acq_rate,
            'propertyKind': inputs.get('propertyKind'), 'areaSqm': _num(inputs, 'areaSqm'),
            'houseCount': inputs.get('houseCount'), 'adjustedArea': inputs.get('adjustedArea'),
            'legalFee': legal, 'registrationFee': regist, 'evictionCost': evict,
            'repairCost': repair, 'interiorCost': interior,
            'assumedRightsAmount': assumed, 'unpaidManagementFee': unpaid,
            'agentCommissionRate': comm_rate, 'loanAmount': loan, 'loanAnnualRate': loan_rate,
            'earlyRepaymentFeeRate': early_rate, 'transferTax': transfer_tax, 'businessTax': business_tax,
        },
        'bidToAppraisalRatio': round(ratio, 2),
        'acquisitionTaxBasis': tax_basis,
        'costs': {
            'acquisitionTax': round(acq_tax), 'legalFee': round(legal), 'registrationFee': round(regist),
            'evictionCost': round(evict), 'repairCost': round(repair), 'interiorCost': round(interior),
            'assumedRightsAmount': round(assumed_applied), 'unpaidManagementFee': round(unpaid),
            'agentCommission': round(commission), 'exitTax': round(exit_tax),
            'loanInterest': round(interest), 'earlyRepaymentFee': round(early_fee),
        },
        'totalAcquisitionCost': round(total_acq),
        'totalExitCost': round(total_exit),
        'totalFinanceCost': round(total_fin),
        'netProfit': round(net),
        'simpleROI': round(simple_roi, 2),
        'annualizedROI': round(annual_roi, 2),
        'warnings': warnings,
        'disclaimer': DISCLAIMER[owner],
    }


# ─────────────────────────── 갭투자 ───────────────────────────
def calc_gap(inputs: dict) -> dict:
    purchase = _num(inputs, 'purchasePrice')
    jeonse = _num(inputs, 'jeonseDeposit')
    sale = _num(inputs, 'expectedSalePrice')
    months = _num(inputs, 'holdingPeriodMonths')
    _require_positive('purchasePrice', purchase)
    if jeonse is None or jeonse < 0:
        raise ROIInputError(f"jeonseDeposit 는 0 이상이어야 합니다 (입력: {jeonse})")
    if jeonse >= purchase:
        raise ROIInputError("전세보증금이 매매가 이상입니다 — 갭 ≤ 0, 투자 성립 불가")
    if sale is None or sale < 0:
        raise ROIInputError(f"expectedSalePrice 는 0 이상이어야 합니다 (입력: {sale})")
    if months is None or months < 1:
        raise ROIInputError(f"holdingPeriodMonths 는 1 이상이어야 합니다 (입력: {months})")

    acq_rate = _num(inputs, 'acquisitionTaxRate', DEFAULT_GAP_ACQUISITION_TAX_RATE)
    holding_tax = _num(inputs, 'annualHoldingTax', 0) or 0
    comm_rate = _num(inputs, 'agentCommissionRate', DEFAULT_AGENT_COMMISSION_RATE)
    loan = _num(inputs, 'loanAmount', 0) or 0
    loan_rate = _num(inputs, 'loanAnnualRate')
    transfer_tax = _num(inputs, 'transferTax')
    drop_rate = _num(inputs, 'reverseJeonseDropRate', DEFAULT_REVERSE_JEONSE_DROP_RATE)

    _require_nonneg('annualHoldingTax', holding_tax)
    _require_nonneg('loanAmount', loan)
    _require_nonneg('transferTax', transfer_tax)
    for name, v in [('acquisitionTaxRate', acq_rate), ('agentCommissionRate', comm_rate),
                    ('loanAnnualRate', loan_rate), ('reverseJeonseDropRate', drop_rate)]:
        _require_rate(name, v)

    warnings: list[str] = []
    gap = purchase - jeonse
    jeonse_ratio = jeonse / purchase * 100
    capital_gain = sale - purchase

    if jeonse_ratio >= JEONSE_RATIO_DANGER:
        warnings.append("전세가율 90% 이상 — 깡통전세 위험. 시세 하락 시 보증금 미반환 가능성이 큽니다")
    elif jeonse_ratio >= JEONSE_RATIO_WARNING:
        warnings.append("전세가율 80% 이상 — 역전세 고위험. 전세금반환보증(HUG/SGI) 가입 여부를 확인하세요")

    acq_tax = purchase * acq_rate
    commission = sale * comm_rate
    holding_total = holding_tax * (months / 12)
    if loan > 0 and loan_rate is None:
        warnings.append("대출 연이율 미입력 — 이자비용이 수익률에 반영되지 않았습니다")
    interest = loan * loan_rate * (months / 12) if (loan > 0 and loan_rate is not None) else 0.0
    if transfer_tax is None:
        warnings.append("양도세 미반영 — 보유기간·주택수·조정대상지역에 따라 세후 수익이 크게 달라집니다")
    transfer_applied = transfer_tax or 0.0
    total_cost = acq_tax + commission + holding_total + interest + transfer_applied

    invested = gap + acq_tax + holding_total
    net = capital_gain - total_cost
    roe = net / invested * 100
    annual_roe = roe * (12 / months)
    leverage = (capital_gain / gap) * (12 / months) * 100

    dropped = jeonse * (1 - drop_rate)
    shortfall = jeonse - dropped
    exceeds_gap = shortfall > gap
    if exceeds_gap:
        warnings.append("역전세 발생 시 필요한 추가 현금이 초기 투자금(갭)을 초과합니다")
    real_net = net - shortfall
    real_roe = real_net / invested * 100
    if net < 0:
        warnings.append("예상 순수익이 마이너스입니다 — 매도가·비용을 재검토하세요")

    return {
        'mode': 'gap',
        'inputs': {
            'purchasePrice': purchase, 'jeonseDeposit': jeonse, 'expectedSalePrice': sale,
            'holdingPeriodMonths': months, 'acquisitionTaxRate': acq_rate,
            'annualHoldingTax': holding_tax, 'agentCommissionRate': comm_rate,
            'loanAmount': loan, 'loanAnnualRate': loan_rate, 'transferTax': transfer_tax,
            'reverseJeonseDropRate': drop_rate,
        },
        'gap': round(gap),
        'jeonseRatio': round(jeonse_ratio, 2),
        'capitalGain': round(capital_gain),
        'costs': {
            'acquisitionTax': round(acq_tax), 'agentCommission': round(commission),
            'holdingTaxTotal': round(holding_total), 'loanInterest': round(interest),
            'transferTax': round(transfer_applied),
        },
        'totalCost': round(total_cost),
        'investedCapital': round(invested),
        'netProfit': round(net),
        'roe': round(roe, 2),
        'annualizedRoe': round(annual_roe, 2),
        'leverageReturn': round(leverage, 2),
        'reverseJeonse': {
            'dropRate': drop_rate,
            'droppedDeposit': round(dropped),
            'shortfall': round(shortfall),
            'exceedsGap': exceeds_gap,
            'realNetProfit': round(real_net),
            'realRoe': round(real_roe, 2),
        },
        'warnings': warnings,
        'disclaimer': DISCLAIMER['gap'],
    }


# ─────────────────────────── 3시나리오 (bid-analysis) ───────────────────────────
def quantify_risks(common: dict, base_result: dict) -> dict:
    """
    bid-analysis 스킬 '리스크 정량화' 표.
    명도 지연의 '보유비용'은 연간 금융비용(대출이자)으로 정의한다 (대출 없으면 0).
    """
    loan = float(common.get('loanAmount') or 0)
    loan_rate = common.get('loanAnnualRate')
    annual_finance = loan * float(loan_rate) if (loan > 0 and loan_rate is not None) else 0.0
    sale = float(base_result['inputs']['expectedSalePrice'])
    repair = float(common.get('repairCost') or 0)
    items = [
        {'risk': '명도 지연 (6개월 추가)', 'probability': 0.15, 'impact': round(annual_finance * 0.5)},
        {'risk': '숨은 권리관계', 'probability': 0.10, 'impact': 5_000_000},
        {'risk': '시장 하락 10%', 'probability': 0.20, 'impact': round(sale * 0.10)},
        {'risk': '수리비 초과', 'probability': 0.20, 'impact': round(repair * 0.5)},
    ]
    for it in items:
        it['expectedCost'] = round(it['probability'] * it['impact'])
    return {'items': items, 'expectedRiskCost': sum(it['expectedCost'] for it in items)}


def run_scenarios(appraisal: float, min_bid: float, fair_value: float, common: dict,
                  cltr_mng_no: str | None = None, sale_basis: str = '') -> dict:
    """
    bid-analysis Step 3~5. common 에는 calc_auction 의 선택 입력(취득세율, 비용, 대출 등)을 담는다.
    """
    _require_positive('appraisalValue', appraisal)
    _require_positive('minBidPrice', min_bid)
    _require_positive('fairValue', fair_value)

    results = {}
    all_warnings: list[str] = []
    for key, sc in SCENARIOS.items():
        inputs = {
            **common,
            'appraisalValue': appraisal,
            'bidPrice': round(min_bid * sc['bid']),
            'expectedSalePrice': round(fair_value * sc['sale']),
            'holdingPeriodMonths': sc['months'],
        }
        r = calc_auction(inputs)
        r['label'] = sc['label']
        r['bidMultiplier'] = sc['bid']
        r['saleMultiplier'] = sc['sale']
        results[key] = r
        for w in r['warnings']:
            if w not in all_warnings:
                all_warnings.append(w)

    base_roi = results['base']['annualizedROI']
    aggressive_bid = results['aggressive']['inputs']['bidPrice']
    cap = round(fair_value * FAIR_VALUE_CAP)
    reference_bid = min(aggressive_bid, cap)
    if base_roi >= VERDICT_ACTIVE:
        verdict, rng = '적극입찰', (round(min_bid * 1.05), round(min_bid * 1.12))
    elif base_roi >= VERDICT_PASSIVE:
        verdict, rng = '소극입찰', (round(min_bid * 1.00), round(min_bid * 1.05))
    else:
        verdict, rng = '보류', None

    rec_bid = None if verdict == '보류' else min(reference_bid, rng[1])
    if rec_bid is not None and rec_bid < min_bid:
        # fair_value 상한이 최저입찰가보다 낮으면 입찰 자체가 시세 대비 불리 → 보류로 강등
        verdict, rec_bid, rng = '보류', None, None
        all_warnings.append(f"fair_value×{FAIR_VALUE_CAP} ({format_price(cap)}) 이 최저입찰가({format_price(min_bid)})보다 낮아 "
                            "현재 회차 입찰은 시세 대비 불리합니다 — 다음 저감 회차 검토 권장")

    rationale = (f"기준 시나리오(최저가×1.05, 시세×1.00, 24개월) 연환산 ROI {base_roi:.1f}% → {verdict}. "
                 f"권고가 상한 = min(공격 시나리오 입찰가 {format_price(aggressive_bid)}, "
                 f"적정가치×{FAIR_VALUE_CAP} {format_price(cap)})")

    return {
        'cltrMngNo': cltr_mng_no,
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'generator': 'scripts/roi_calculator.py scenarios',
        'appraisalValue': appraisal,
        'minBidPrice': min_bid,
        'fairValue': fair_value,
        'expectedSalePriceBasis': sale_basis,
        'commonInputs': common,
        'scenarios': results,
        'recommendation': {
            'verdict': verdict,
            'bidPrice': rec_bid,
            'bidRange': list(rng) if rng else None,
            'referenceBidPrice': reference_bid,
            'fairValueCap': cap,
            'baseAnnualizedROI': base_roi,
            'rationale': rationale,
        },
        'risks': quantify_risks(common, results['base']),
        'warnings': all_warnings,
        'disclaimer': DISCLAIMER[(common.get('ownerType') or 'individual')],
    }


# ─────────────────────────── 출력 포맷 ───────────────────────────
def _man(v) -> str:
    return f"{round(v / 1e4):,}만 원"


def render_auction(r: dict) -> str:
    i, c = r['inputs'], r['costs']
    owner = '개인' if r['ownerType'] == 'individual' else '매매사업자'
    lines = [
        "## 경매/공매 ROI 분석 결과", "",
        "### 기본 정보",
        f"- 투자 주체: {owner}",
        f"- 감정가: {format_price(i['appraisalValue'])} 원",
        f"- 입찰가: {format_price(i['bidPrice'])} 원 (낙찰가율 {r['bidToAppraisalRatio']:.1f}%)",
        f"- 예상 매도가: {format_price(i['expectedSalePrice'])} 원",
        f"- 보유기간: {i['holdingPeriodMonths']:.0f}개월", "",
        "### 비용 상세",
        "| 항목 | 금액 |", "|------|------|",
        f"| 취득세 ({i['acquisitionTaxRate']*100:.2f}%{' · ' + r['acquisitionTaxBasis']['basis'] if r.get('acquisitionTaxBasis') else ''}) | {_man(c['acquisitionTax'])} |",
        f"| 법무비용 | {_man(c['legalFee'])} |",
        f"| 등록세/등기비용 | {_man(c['registrationFee'])} |",
        f"| 명도비용 | {_man(c['evictionCost'])} |",
        f"| 수리비+인테리어 | {_man(c['repairCost'] + c['interiorCost'])} |",
        f"| 권리분석 인수금액 | {_man(c['assumedRightsAmount'])} |",
        f"| 체납관리비 | {_man(c['unpaidManagementFee'])} |",
        f"| **취득비용 합계** | **{format_price(r['totalAcquisitionCost'])} 원** |",
        f"| 매도 중개수수료 | {_man(c['agentCommission'])} |",
        f"| 양도세/사업소득세 | {_man(c['exitTax'])} |",
        f"| **매도비용 합계** | **{_man(r['totalExitCost'])}** |",
        f"| 대출이자 | {_man(c['loanInterest'])} |",
        f"| 중도상환수수료 | {_man(c['earlyRepaymentFee'])} |",
        f"| **금융비용 합계** | **{_man(r['totalFinanceCost'])}** |", "",
        "### 수익 분석",
        f"- 순수익: **{_man(r['netProfit'])}**",
        f"- 단순 ROI: {r['simpleROI']:.1f}%",
        f"- 연환산 ROI: **{r['annualizedROI']:.1f}%**", "",
    ]
    if r['warnings']:
        lines += ["### ⚠️ 경고"] + [f"- {w}" for w in r['warnings']] + [""]
    lines.append(f"> {r['disclaimer']}")
    return "\n".join(lines)


def render_gap(r: dict) -> str:
    i, c, rj = r['inputs'], r['costs'], r['reverseJeonse']
    lines = [
        "## 갭투자 ROI 분석 결과", "",
        "### 기본 정보",
        f"- 매매가: {format_price(i['purchasePrice'])} 원",
        f"- 전세보증금: {format_price(i['jeonseDeposit'])} 원 (전세가율 {r['jeonseRatio']:.1f}%)",
        f"- 갭(자기자본): {_man(r['gap'])}",
        f"- 예상 매도가: {format_price(i['expectedSalePrice'])} 원",
        f"- 보유기간: {i['holdingPeriodMonths']:.0f}개월", "",
        "### 비용 상세",
        "| 항목 | 금액 |", "|------|------|",
        f"| 취득세 | {_man(c['acquisitionTax'])} |",
        f"| 매도 중개수수료 | {_man(c['agentCommission'])} |",
        f"| 보유세 합계 | {_man(c['holdingTaxTotal'])} |",
        f"| 대출이자 | {_man(c['loanInterest'])} |",
        f"| 양도세 | {_man(c['transferTax'])} |",
        f"| **총비용** | **{_man(r['totalCost'])}** |", "",
        "### 수익 분석",
        f"- 시세차익: {_man(r['capitalGain'])}",
        f"- 순수익: **{_man(r['netProfit'])}**",
        f"- 투입자본: {_man(r['investedCapital'])}",
        f"- ROE: **{r['roe']:.1f}%**",
        f"- 연환산 ROE: **{r['annualizedRoe']:.1f}%**",
        f"- 레버리지 수익률: {r['leverageReturn']:.1f}% (참고)", "",
        f"### 역전세 시뮬레이션 (전세가 {rj['dropRate']*100:.0f}% 하락 가정)",
        f"- 하락 후 전세: {_man(rj['droppedDeposit'])}",
        f"- 보증금 부족액: {_man(rj['shortfall'])}",
        f"- 역전세 반영 실질 순수익: {_man(rj['realNetProfit'])}",
        f"- 역전세 반영 실질 ROE: {rj['realRoe']:.1f}%", "",
    ]
    if r['warnings']:
        lines += ["### ⚠️ 경고"] + [f"- {w}" for w in r['warnings']] + [""]
    lines.append(f"> {r['disclaimer']}")
    return "\n".join(lines)


def render_scenarios(r: dict) -> str:
    lines = [
        f"## 입찰 시나리오 분석 — {r.get('cltrMngNo') or ''}", "",
        f"- 감정가 {format_price(r['appraisalValue'])} / 최저입찰가 {format_price(r['minBidPrice'])} "
        f"/ 적정가치 {format_price(r['fairValue'])}", "",
        "| 시나리오 | 입찰가 | 예상매도가 | 낙찰가율 | 취득비용합계 | 순수익 | 연환산ROI | 경고 |",
        "|---------|-------|----------|---------|------------|-------|---------|------|",
    ]
    icons = {'conservative': '🔵', 'base': '🟡', 'aggressive': '🔴'}
    for k, s in r['scenarios'].items():
        lines.append(f"| {icons[k]} {s['label']} | {format_price(s['inputs']['bidPrice'])} | "
                     f"{format_price(s['inputs']['expectedSalePrice'])} | {s['bidToAppraisalRatio']:.1f}% | "
                     f"{format_price(s['totalAcquisitionCost'])} | {_man(s['netProfit'])} | "
                     f"{s['annualizedROI']:.1f}% | {len(s['warnings'])} |")
    rec = r['recommendation']
    lines += ["", f"**판정: {rec['verdict']}** — 권고 입찰가: "
              f"{format_price(rec['bidPrice']) if rec['bidPrice'] else '—'}",
              f"- {rec['rationale']}",
              f"- 예상 리스크 비용(기대값): {_man(r['risks']['expectedRiskCost'])}", ""]
    if r['warnings']:
        lines += ["### ⚠️ 경고"] + [f"- {w}" for w in r['warnings']] + [""]
    lines.append(f"> {r['disclaimer']}")
    return "\n".join(lines)


# ─────────────────────────── CLI ───────────────────────────
def _add_common_cost_args(p: argparse.ArgumentParser):
    p.add_argument('--owner', choices=['individual', 'business'], default=None, help='투자 주체 (기본 individual)')
    p.add_argument('--acq-tax-rate', type=float, default=None, help='취득세율 소수 (기본 0.046). --kind 를 주면 자동 산정')
    p.add_argument('--kind', choices=PROPERTY_KINDS, default=None, help='물건 종류 → 취득세율 자동 산정 (house 는 입찰가·면적·주택수 반영)')
    p.add_argument('--area-sqm', type=float, default=None, help='전용면적 ㎡ (house 농특세 판정)')
    p.add_argument('--house-count', type=int, default=None, help='취득 후 보유 주택 수 (기본 1)')
    p.add_argument('--adjusted', action='store_true', default=None, help='조정대상지역')
    p.add_argument('--legal-fee', type=float, default=None)
    p.add_argument('--registration-fee', type=float, default=None)
    p.add_argument('--eviction-cost', type=float, default=None)
    p.add_argument('--repair-cost', type=float, default=None)
    p.add_argument('--interior-cost', type=float, default=None)
    p.add_argument('--assumed-rights', type=float, default=None, help='권리분석 인수금액 (미입력 시 경고)')
    p.add_argument('--unpaid-mgmt-fee', type=float, default=None)
    p.add_argument('--commission-rate', type=float, default=None, help='매도 중개수수료율 (기본 0.005)')
    p.add_argument('--loan', type=float, default=None, help='대출금액')
    p.add_argument('--loan-rate', type=float, default=None, help='대출 연이율 소수')
    p.add_argument('--early-fee-rate', type=float, default=None)
    p.add_argument('--transfer-tax', type=float, default=None, help='양도세 (개인)')
    p.add_argument('--business-tax', type=float, default=None, help='사업소득세 (사업자)')


_COMMON_MAP = {
    'owner': 'ownerType', 'acq_tax_rate': 'acquisitionTaxRate', 'legal_fee': 'legalFee',
    'registration_fee': 'registrationFee', 'eviction_cost': 'evictionCost', 'repair_cost': 'repairCost',
    'interior_cost': 'interiorCost', 'assumed_rights': 'assumedRightsAmount',
    'unpaid_mgmt_fee': 'unpaidManagementFee', 'commission_rate': 'agentCommissionRate',
    'loan': 'loanAmount', 'loan_rate': 'loanAnnualRate', 'early_fee_rate': 'earlyRepaymentFeeRate',
    'transfer_tax': 'transferTax', 'business_tax': 'businessTax',
    'kind': 'propertyKind', 'area_sqm': 'areaSqm', 'house_count': 'houseCount', 'adjusted': 'adjustedArea',
}


def _collect(args, extra_map: dict) -> dict:
    """--json-in 파일 + CLI 인자 병합 (CLI 인자가 우선)."""
    inputs = {}
    if getattr(args, 'json_in', None):
        with open(args.json_in, encoding='utf-8') as f:
            inputs.update(json.load(f))
    for attr, key in {**_COMMON_MAP, **extra_map}.items():
        v = getattr(args, attr, None)
        if v is not None:
            inputs[key] = v
    return inputs


def _emit(result: dict, text: str, args):
    if args.format == 'json':
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(text)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"\n저장: {out}")


def main(argv=None):
    parser = argparse.ArgumentParser(description='부동산 투자 ROI 계산기 (auction / gap / scenarios)')
    sub = parser.add_subparsers(dest='command', required=True)

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument('--json-in', help='입력 파라미터 JSON 파일 (변수명은 SKILL.md camelCase)')
    shared.add_argument('--output', help='결과 JSON 저장 경로')
    shared.add_argument('--format', choices=['md', 'json'], default='md', help='콘솔 출력 형식')

    pa = sub.add_parser('auction', parents=[shared], help='경매/공매 ROI')
    pa.add_argument('--appraisal', type=float, help='감정가 (원)')
    pa.add_argument('--bid', type=float, help='입찰가 (원)')
    pa.add_argument('--sale', type=float, help='예상 매도가 (원)')
    pa.add_argument('--months', type=float, help='보유기간 (월)')
    _add_common_cost_args(pa)

    pg = sub.add_parser('gap', parents=[shared], help='갭투자 ROE')
    pg.add_argument('--purchase', type=float, help='매매가 (원)')
    pg.add_argument('--jeonse', type=float, help='전세보증금 (원)')
    pg.add_argument('--sale', type=float, help='예상 매도가 (원)')
    pg.add_argument('--months', type=float, help='보유기간 (월)')
    pg.add_argument('--acq-tax-rate', type=float, default=None, help='취득세율 (기본 0.011)')
    pg.add_argument('--holding-tax', type=float, default=None, help='연간 보유세')
    pg.add_argument('--commission-rate', type=float, default=None)
    pg.add_argument('--loan', type=float, default=None)
    pg.add_argument('--loan-rate', type=float, default=None)
    pg.add_argument('--transfer-tax', type=float, default=None)
    pg.add_argument('--drop-rate', type=float, default=None, help='역전세 하락률 (기본 0.10)')

    ps = sub.add_parser('scenarios', parents=[shared], help='보수/기준/공격 3시나리오 + 권고')
    ps.add_argument('--cltr-mng-no', help='물건관리번호 (출력 파일 식별용)')
    ps.add_argument('--appraisal', type=float, help='감정가 (원)')
    ps.add_argument('--min-bid', type=float, help='현재 회차 최저입찰가 (원)')
    ps.add_argument('--fair-value', type=float, help='적정가치 = expectedSalePrice 기준값 (원)')
    ps.add_argument('--sale-basis', default='', help='적정가치 산출 근거 메모')
    _add_common_cost_args(ps)

    pt = sub.add_parser('tax', parents=[shared], help='취득세율만 조회')
    pt.add_argument('--kind', choices=PROPERTY_KINDS, required=True)
    pt.add_argument('--price', type=float, help='취득가액 (house 필수)')
    pt.add_argument('--area-sqm', type=float)
    pt.add_argument('--house-count', type=int, default=1)
    pt.add_argument('--adjusted', action='store_true')

    args = parser.parse_args(argv)
    try:
        if args.command == 'tax':
            r = acquisition_tax_rate(args.kind, args.price, args.area_sqm, args.house_count, args.adjusted)
            text = (f"취득세율 {r['rate']*100:.2f}% — {r['basis']}\n"
                    + "\n".join(f"- {n}" for n in r['notes']))
            _emit(r, text, args)
        elif args.command == 'auction':
            inputs = _collect(args, {'appraisal': 'appraisalValue', 'bid': 'bidPrice',
                                     'sale': 'expectedSalePrice', 'months': 'holdingPeriodMonths'})
            r = calc_auction(inputs)
            _emit(r, render_auction(r), args)
        elif args.command == 'gap':
            inputs = {}
            if args.json_in:
                inputs.update(json.load(open(args.json_in, encoding='utf-8')))
            for attr, key in {'purchase': 'purchasePrice', 'jeonse': 'jeonseDeposit',
                              'sale': 'expectedSalePrice', 'months': 'holdingPeriodMonths',
                              'acq_tax_rate': 'acquisitionTaxRate', 'holding_tax': 'annualHoldingTax',
                              'commission_rate': 'agentCommissionRate', 'loan': 'loanAmount',
                              'loan_rate': 'loanAnnualRate', 'transfer_tax': 'transferTax',
                              'drop_rate': 'reverseJeonseDropRate'}.items():
                v = getattr(args, attr, None)
                if v is not None:
                    inputs[key] = v
            r = calc_gap(inputs)
            _emit(r, render_gap(r), args)
        else:
            inputs = _collect(args, {'appraisal': 'appraisalValue', 'min_bid': 'minBidPrice',
                                     'fair_value': 'fairValue', 'cltr_mng_no': 'cltrMngNo',
                                     'sale_basis': 'expectedSalePriceBasis'})
            appraisal = inputs.pop('appraisalValue', None)
            min_bid = inputs.pop('minBidPrice', None)
            fair = inputs.pop('fairValue', None)
            cltr = inputs.pop('cltrMngNo', None)
            basis = inputs.pop('expectedSalePriceBasis', '')
            if appraisal is None or min_bid is None or fair is None:
                raise ROIInputError("scenarios 에는 --appraisal, --min-bid, --fair-value 가 필요합니다")
            r = run_scenarios(appraisal, min_bid, fair, inputs, cltr_mng_no=cltr, sale_basis=basis)
            _emit(r, render_scenarios(r), args)
    except ROIInputError as e:
        print(f"[!] 입력 오류: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
