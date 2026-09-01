"""roi_calculator.py — references/*.md 의 예제값과 일치해야 한다."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

from roi_calculator import (ROIInputError, calc_auction, calc_gap,  # noqa: E402
                            run_scenarios, main)


def test_auction_worked_example():
    """auction-formulas.md 예시: 3.825억/4.25억/4.09억/6개월 → ROI ≈ 3.4%"""
    r = calc_auction({'appraisalValue': 425_000_000, 'bidPrice': 382_500_000,
                      'expectedSalePrice': 409_000_000, 'holdingPeriodMonths': 6})
    assert r['bidToAppraisalRatio'] == 90.0
    assert r['costs']['acquisitionTax'] == 17_595_000
    assert r['totalAcquisitionCost'] == 400_095_000
    assert r['costs']['agentCommission'] == 2_045_000
    assert r['netProfit'] == 6_860_000
    assert abs(r['annualizedROI'] - 3.43) < 0.01
    # 미입력 경고 2개 (권리분석, 양도세)
    assert any('권리분석' in w for w in r['warnings'])
    assert any('양도세' in w for w in r['warnings'])


def test_auction_all_costs_and_loan():
    r = calc_auction({'appraisalValue': 100_000_000, 'bidPrice': 80_000_000, 'expectedSalePrice': 120_000_000,
                      'holdingPeriodMonths': 12, 'acquisitionTaxRate': 0.011, 'legalFee': 300_000,
                      'registrationFee': 500_000, 'evictionCost': 1_000_000, 'repairCost': 2_000_000,
                      'assumedRightsAmount': 0, 'loanAmount': 40_000_000, 'loanAnnualRate': 0.05,
                      'transferTax': 3_000_000})
    assert r['costs']['acquisitionTax'] == 880_000
    assert r['totalAcquisitionCost'] == 80_000_000 + 880_000 + 300_000 + 500_000 + 1_000_000 + 2_000_000
    assert r['costs']['loanInterest'] == 2_000_000
    assert r['costs']['earlyRepaymentFee'] == 400_000
    assert r['totalExitCost'] == 600_000 + 3_000_000
    assert r['warnings'] == []  # 모두 입력 → 경고 없음


def test_auction_warnings():
    r = calc_auction({'appraisalValue': 100, 'bidPrice': 120, 'expectedSalePrice': 50,
                      'holdingPeriodMonths': 1, 'ownerType': 'business', 'loanAmount': 10})
    msgs = ' '.join(r['warnings'])
    assert '감정가를 초과' in msgs
    assert '사업소득세' in msgs
    assert '대출 연이율' in msgs
    assert '마이너스' in msgs


@pytest.mark.parametrize('bad', [
    {'appraisalValue': 0, 'bidPrice': 1, 'expectedSalePrice': 1, 'holdingPeriodMonths': 1},
    {'appraisalValue': 1, 'bidPrice': -1, 'expectedSalePrice': 1, 'holdingPeriodMonths': 1},
    {'appraisalValue': 1, 'bidPrice': 1, 'expectedSalePrice': 1, 'holdingPeriodMonths': 0},
    {'appraisalValue': 1, 'bidPrice': 1, 'expectedSalePrice': 1, 'holdingPeriodMonths': 1, 'acquisitionTaxRate': 4.6},
    {'appraisalValue': 1, 'bidPrice': 1, 'expectedSalePrice': 1, 'holdingPeriodMonths': 1, 'repairCost': -5},
    {'appraisalValue': 1, 'bidPrice': 1, 'expectedSalePrice': 1, 'holdingPeriodMonths': 1, 'ownerType': 'x'},
])
def test_auction_validation(bad):
    with pytest.raises(ROIInputError):
        calc_auction(bad)


def test_gap_worked_example():
    """gap-formulas.md 예시: 4.09억/3.18억/4.3억/24개월 → ROE 15.0%, 연환산 7.5%, 역전세 -18.3%"""
    r = calc_gap({'purchasePrice': 409_000_000, 'jeonseDeposit': 318_000_000,
                  'expectedSalePrice': 430_000_000, 'holdingPeriodMonths': 24})
    assert r['gap'] == 91_000_000
    assert abs(r['jeonseRatio'] - 77.75) < 0.01
    assert r['costs']['acquisitionTax'] == 4_499_000
    assert r['netProfit'] == 14_351_000
    assert abs(r['roe'] - 15.03) < 0.01
    assert abs(r['annualizedRoe'] - 7.51) < 0.01
    assert abs(r['leverageReturn'] - 11.54) < 0.01
    assert r['reverseJeonse']['shortfall'] == 31_800_000
    assert r['reverseJeonse']['exceedsGap'] is False
    assert abs(r['reverseJeonse']['realRoe'] - (-18.27)) < 0.01


def test_gap_jeonse_ratio_warnings():
    r = calc_gap({'purchasePrice': 100, 'jeonseDeposit': 85, 'expectedSalePrice': 100, 'holdingPeriodMonths': 12})
    assert any('80%' in w for w in r['warnings'])
    r = calc_gap({'purchasePrice': 100, 'jeonseDeposit': 95, 'expectedSalePrice': 100, 'holdingPeriodMonths': 12})
    assert any('깡통' in w for w in r['warnings'])
    with pytest.raises(ROIInputError):
        calc_gap({'purchasePrice': 100, 'jeonseDeposit': 100, 'expectedSalePrice': 100, 'holdingPeriodMonths': 12})


def test_scenarios_structure_and_verdict():
    r = run_scenarios(250_000_000, 200_000_000, 255_000_000,
                      {'acquisitionTaxRate': 0.011, 'assumedRightsAmount': 0, 'transferTax': 0},
                      cltr_mng_no='X')
    assert set(r['scenarios']) == {'conservative', 'base', 'aggressive'}
    assert r['scenarios']['base']['inputs']['bidPrice'] == 210_000_000
    assert r['scenarios']['base']['inputs']['holdingPeriodMonths'] == 24
    assert r['scenarios']['aggressive']['inputs']['expectedSalePrice'] == round(255_000_000 * 1.1)
    assert r['recommendation']['verdict'] in ('적극입찰', '소극입찰', '보류')
    assert r['recommendation']['fairValueCap'] == round(255_000_000 * 0.85)
    assert r['risks']['expectedRiskCost'] > 0


def test_scenarios_active_verdict():
    # 시세가 최저가의 2배면 기준 ROI가 15%를 훌쩍 넘는다
    r = run_scenarios(100_000_000, 50_000_000, 100_000_000,
                      {'assumedRightsAmount': 0, 'transferTax': 0})
    assert r['recommendation']['verdict'] == '적극입찰'
    assert r['recommendation']['bidPrice'] == min(56_000_000, 85_000_000)
    assert r['recommendation']['bidPrice'] <= r['recommendation']['bidRange'][1]


def test_scenarios_hold_when_cap_below_min_bid():
    # fair_value×0.85 < 최저가 → 보류 강등
    r = run_scenarios(100_000_000, 100_000_000, 100_000_000, {'assumedRightsAmount': 0, 'transferTax': 0})
    assert r['recommendation']['verdict'] == '보류'
    assert r['recommendation']['bidPrice'] is None


def test_cli_auction_json(tmp_path):
    out = tmp_path / 'r.json'
    rc = main(['auction', '--appraisal', '425000000', '--bid', '382500000', '--sale', '409000000',
               '--months', '6', '--format', 'json', '--output', str(out)])
    assert rc == 0
    d = json.loads(out.read_text(encoding='utf-8'))
    assert d['netProfit'] == 6_860_000


def test_cli_json_in_and_override(tmp_path):
    params = tmp_path / 'p.json'
    params.write_text(json.dumps({'appraisalValue': 100, 'bidPrice': 90, 'expectedSalePrice': 120,
                                  'holdingPeriodMonths': 12, 'assumedRightsAmount': 0}), encoding='utf-8')
    out = tmp_path / 'r.json'
    rc = main(['auction', '--json-in', str(params), '--bid', '80', '--format', 'json', '--output', str(out)])
    assert rc == 0
    assert json.loads(out.read_text())['inputs']['bidPrice'] == 80.0


def test_cli_validation_exit_code():
    rc = main(['auction', '--appraisal', '0', '--bid', '1', '--sale', '1', '--months', '1'])
    assert rc == 2


def test_cli_subprocess_runs():
    r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'roi_calculator.py'), 'gap',
                        '--purchase', '409000000', '--jeonse', '318000000', '--sale', '430000000',
                        '--months', '24'], capture_output=True, text=True)
    assert r.returncode == 0
    assert 'ROE' in r.stdout
