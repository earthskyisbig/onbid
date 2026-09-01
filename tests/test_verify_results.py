"""verify_results.py — 오프라인 검증 로직 (API 호출 없음)."""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

from roi_calculator import run_scenarios  # noqa: E402
from verify_results import verify_phase1, verify_phase3  # noqa: E402

NOW = datetime(2026, 9, 2, 12, 0)


def _prop(**over):
    p = {
        'cltrMngNo': '2024-18146-006', 'onbidCltrNm': '호안빌 101호', 'pbctCdtnNo': 1, 'pbctNsq': '034',
        'cltrBidBgngDt': '202609281400', 'cltrBidEndDt': '202609301700',
        'apslEvlAmt': 424_000_000.0, 'lowstBidPrc': 42_400_000.0, 'apslRatio': 10.0,
        'cltrUsgSclsCtgrNm': '다세대주택',
        'rounds': [
            {'pbctNsq': '034', 'pbctCdtnNo': 1, 'cltrBidBgngDt': '202609281400', 'cltrBidEndDt': '202609301700', 'lowstBidPrc': 42_400_000.0},
            {'pbctNsq': '035', 'pbctCdtnNo': 2, 'cltrBidBgngDt': '202610061400', 'cltrBidEndDt': '202610071700', 'lowstBidPrc': 38_160_000.0},
        ],
    }
    p.update(over)
    return p


def _write_search(tmp_path, props, type_filter=None):
    f = tmp_path / '01_search_results.json'
    f.write_text(json.dumps({'filters': {'type': type_filter}, 'properties': props}, ensure_ascii=False), encoding='utf-8')
    return f


def test_phase1_pass(tmp_path):
    rep = verify_phase1(_write_search(tmp_path, [_prop()], '다세대'), True, NOW)
    assert rep['summary'] == {'PASS': 1, 'WARN': 0, 'FAIL': 0}
    assert rep['failures'] == []


def test_phase1_detects_wrong_round_and_expired(tmp_path):
    wrong = _prop(pbctCdtnNo=2, pbctNsq='035', lowstBidPrc=38_160_000.0, cltrBidBgngDt='202610061400', cltrBidEndDt='202610071700')
    expired = _prop(cltrMngNo='X', cltrBidEndDt='202608011700')
    rep = verify_phase1(_write_search(tmp_path, [wrong, expired]), True, NOW)
    assert rep['summary']['FAIL'] == 2
    assert '기대 회차 034' in rep['results'][0]['checks']['round_selection']['detail']
    assert '만료' in rep['results'][1]['checks']['round_selection']['detail']


def test_phase1_price_logic_and_usage(tmp_path):
    bad_ratio = _prop(apslRatio=100.0)                       # 저장된 비율이 직접계산(10%)과 불일치
    over = _prop(cltrMngNo='Y', lowstBidPrc=500_000_000.0, apslRatio=None)
    mixed = _prop(cltrMngNo='Z', cltrUsgSclsCtgrNm='판매시설', onbidCltrNm='OO아파트 상가')
    rep = verify_phase1(_write_search(tmp_path, [bad_ratio, over, mixed], '아파트'), True, NOW)
    r = {x['cltrMngNo']: x for x in rep['results']}
    assert r['2024-18146-006']['checks']['price_logic']['status'] == 'FAIL'
    assert r['Y']['checks']['price_logic']['status'] == 'FAIL'
    assert r['Z']['checks']['usage_category']['status'] == 'WARN'   # 물건명에만 '아파트' → 혼입 의심
    assert r['2024-18146-006']['checks']['usage_category']['status'] == 'FAIL'


def test_phase3_matches_roi_calculator_output(tmp_path):
    search = _write_search(tmp_path, [_prop()])
    st = run_scenarios(424_000_000, 42_400_000, 60_000_000, {'assumedRightsAmount': 0, 'transferTax': 0},
                       cltr_mng_no='2024-18146-006')
    (tmp_path / '03_bid_strategy_2024-18146-006.json').write_text(json.dumps(st), encoding='utf-8')
    rep = verify_phase3(search, str(tmp_path / '03_bid_strategy_*.json'), NOW)
    assert rep['summary'] == {'PASS': 1, 'WARN': 0, 'FAIL': 0}
    assert rep['results'][0]['checks']['roi_recompute']['status'] == 'PASS'


def test_phase3_detects_tampered_roi_and_wrong_inputs(tmp_path):
    search = _write_search(tmp_path, [_prop()])
    st = run_scenarios(424_000_000, 42_400_000, 60_000_000, {'assumedRightsAmount': 0, 'transferTax': 0},
                       cltr_mng_no='2024-18146-006')
    st['scenarios']['base']['annualizedROI'] += 5          # 조작된 ROI
    st['appraisalValue'] = 400_000_000                     # 감정가 불일치
    st['minBidPrice'] = 38_160_000                         # 다음 회차 최저가 → WARN
    (tmp_path / '03_bid_strategy_2024-18146-006.json').write_text(json.dumps(st), encoding='utf-8')
    rep = verify_phase3(search, str(tmp_path / '03_bid_strategy_*.json'), NOW)
    c = rep['results'][0]['checks']
    assert c['appraisal_value']['status'] == 'FAIL'
    assert c['min_bid_price']['status'] == 'WARN'
    assert c['roi_recompute']['status'] == 'FAIL'
    assert rep['summary']['FAIL'] == 1


def test_phase3_legacy_schema_warns(tmp_path):
    search = _write_search(tmp_path, [_prop()])
    legacy = {'cltrMngNo': '2024-18146-006', 'appraisalValue': 424_000_000,
              'currentRound': {'minBidPrice': 42_400_000}, 'scenarios': {'base': {'roi_pct': 9.5}}}
    (tmp_path / '03_bid_strategy_2024-18146-006.json').write_text(json.dumps(legacy), encoding='utf-8')
    rep = verify_phase3(search, str(tmp_path / '03_bid_strategy_*.json'), NOW)
    c = rep['results'][0]['checks']
    assert c['appraisal_value']['status'] == 'PASS' and c['min_bid_price']['status'] == 'PASS'
    assert c['roi_recompute']['status'] == 'WARN'
