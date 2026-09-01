#!/usr/bin/env python3
"""
data-verifier 에이전트의 결정론적 구현.
(.claude/agents/data-verifier.md 체크리스트 1~4를 코드로 수행)

    # Phase 1.5 — 검색 결과 검증 (회차 선택·가격 논리·용도 분류)
    python3 scripts/verify_results.py phase1
    python3 scripts/verify_results.py phase1 --offline      # API 재조회 없이 rounds 배열로만 검증

    # Phase 3.5 — 입찰전략 입력값 대조 + ROI 재계산 대조
    python3 scripts/verify_results.py phase3

종료 코드: 0 = FAIL 없음, 1 = FAIL 있음 (오케스트레이터는 1이면 사용자에게 먼저 보고)
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORKSPACE, get_key, onbid_get, to_float  # noqa: E402
from search_properties import (compute_apsl_ratio, resolve_type_keyword,  # noqa: E402
                               select_current_round)

RATIO_MIN, RATIO_MAX = 5.0, 100.0  # 감정가 대비 최저입찰가 정상 범위(%)
MONEY_TOL = 1.0                   # 금액 대조 허용 오차(원)
ROI_TOL = 0.05                    # ROI 재계산 허용 오차(%p)


def _status(checks: dict) -> str:
    vals = [v['status'] if isinstance(v, dict) else v for v in checks.values()]
    if 'FAIL' in vals:
        return 'FAIL'
    if 'WARN' in vals:
        return 'WARN'
    return 'PASS'


def _chk(status: str, detail: str = '') -> dict:
    return {'status': status, 'detail': detail}


# ─────────────────────────── Phase 1 ───────────────────────────
def check_round_selection(prop: dict, now: datetime, offline: bool, key=None) -> dict:
    """채택 회차가 '종료되지 않은 회차 중 가장 이른 회차'인지, 만료되지 않았는지."""
    end = str(prop.get('cltrBidEndDt') or '')
    now_s = now.strftime('%Y%m%d%H%M')
    if end and end < now_s:
        return _chk('FAIL', f"채택 회차 {prop.get('pbctNsq')} 입찰종료 {end} 가 현재({now_s}) 이전 — 만료 데이터")

    rounds = prop.get('rounds') or []
    source = 'result.rounds'
    if not offline:
        time.sleep(0.5)
        items, err = onbid_get('OnbidRlstDtlSrvc2', 'getRlstDtlInf2',
                               {'cltrMngNo': prop.get('cltrMngNo')}, rows=100, key=key)
        if err:
            return _chk('WARN', f"API 재조회 실패({err}) — 저장된 rounds 로 대체 검증")
        elif items:
            rounds = items
            source = 'api'
    if not rounds:
        return _chk('WARN', '회차 목록 없음 — 검증 불가 (search_properties.py 재실행 권장)')

    expected = select_current_round(rounds, now)
    exp_id = str(expected.get('pbctCdtnNo') or expected.get('pbctNsq'))
    got_id = str(prop.get('pbctCdtnNo') or prop.get('pbctNsq'))
    if exp_id != got_id:
        return _chk('FAIL', f"채택 회차 {prop.get('pbctNsq')}(cdtn {prop.get('pbctCdtnNo')}) ≠ "
                            f"기대 회차 {expected.get('pbctNsq')}(cdtn {expected.get('pbctCdtnNo')}) [source={source}]")
    exp_price = to_float(expected.get('lowstBidPrcIndctCont') or expected.get('lowstBidPrc'))
    if abs(exp_price - to_float(prop.get('lowstBidPrc'))) > MONEY_TOL:
        return _chk('FAIL', f"채택 회차 최저가 {prop.get('lowstBidPrc')} ≠ 기대 {exp_price} [source={source}]")
    return _chk('PASS', f"{len(rounds)}개 회차 중 {prop.get('pbctNsq')} 채택 확인 [source={source}]")


def check_price_logic(prop: dict) -> dict:
    low = to_float(prop.get('lowstBidPrc'))
    apsl = to_float(prop.get('apslEvlAmt'))
    if not low or not apsl:
        return _chk('WARN', f"최저가/감정가 누락 (low={low}, apsl={apsl})")
    if low > apsl + MONEY_TOL:
        return _chk('FAIL', f"최저입찰가 {low:,.0f} > 감정가 {apsl:,.0f}")
    ratio = compute_apsl_ratio(low, apsl)
    stored = prop.get('apslRatio')
    if stored is not None and abs(float(stored) - ratio) > 0.5:
        return _chk('FAIL', f"저장된 apslRatio {stored} ≠ 직접계산 {ratio} (API 필드 오염 의심)")
    if ratio < RATIO_MIN:
        return _chk('WARN', f"감정가 대비 {ratio}% — 극단치. 지분매각·데이터 오류 여부 확인")
    return _chk('PASS', f"최저가/감정가 = {ratio}%")


def check_usage(prop: dict, type_filter: str | None) -> dict:
    if not type_filter:
        return _chk('SKIP', '용도 필터 없음')
    kw = resolve_type_keyword(type_filter)
    usage = prop.get('cltrUsgSclsCtgrNm') or ''
    if kw in usage:
        return _chk('PASS', f"소분류 '{usage}' ∋ '{kw}'")
    name_hit = kw in (prop.get('onbidCltrNm') or '')
    return _chk('FAIL' if not name_hit else 'WARN',
                f"소분류 '{usage}' 에 '{kw}' 없음" + (" (물건명에는 포함 — 혼입 의심)" if name_hit else ''))


def verify_phase1(search_path: Path, offline: bool, now: datetime, type_override: str | None = None) -> dict:
    data = json.loads(search_path.read_text(encoding='utf-8'))
    type_filter = type_override or (data.get('filters') or {}).get('type')
    key = None if offline else get_key('ONBID_API_KEY')
    results, failures = [], []
    for prop in data.get('properties', []):
        checks = {
            'round_selection': check_round_selection(prop, now, offline, key),
            'price_logic': check_price_logic(prop),
            'usage_category': check_usage(prop, type_filter),
        }
        verdict = _status(checks)
        results.append({'cltrMngNo': prop.get('cltrMngNo'), 'onbidCltrNm': prop.get('onbidCltrNm'),
                        'checks': checks, 'verdict': verdict})
        if verdict == 'FAIL':
            failures.append({'cltrMngNo': prop.get('cltrMngNo'),
                             'reasons': [f"{k}: {v['detail']}" for k, v in checks.items() if v['status'] == 'FAIL']})
    return {
        'verified_at': now.strftime('%Y-%m-%dT%H:%M:%S'),
        'phase': 'phase1', 'source': str(search_path), 'mode': 'offline' if offline else 'online',
        'type_filter': type_filter,
        'checked_cltrMngNo': [r['cltrMngNo'] for r in results],
        'summary': {s: sum(1 for r in results if r['verdict'] == s) for s in ('PASS', 'WARN', 'FAIL')},
        'results': results, 'failures': failures,
    }


# ─────────────────────────── Phase 3 ───────────────────────────
def _find(d: dict, *paths, default=None):
    """여러 후보 경로('a.b.c') 중 처음 존재하는 값."""
    for path in paths:
        cur = d
        ok = True
        for part in path.split('.'):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return default


def verify_phase3(search_path: Path, strategy_glob: str, now: datetime) -> dict:
    from roi_calculator import calc_auction, ROIInputError
    search = json.loads(search_path.read_text(encoding='utf-8'))
    by_id = {p.get('cltrMngNo'): p for p in search.get('properties', [])}
    results, failures = [], []
    for path in sorted(glob.glob(strategy_glob)):
        st = json.loads(Path(path).read_text(encoding='utf-8'))
        cid = st.get('cltrMngNo')
        checks = {}
        prop = by_id.get(cid)
        if not prop:
            checks['source_match'] = _chk('FAIL', f"{cid} 가 {search_path.name} 에 없음")
        else:
            checks['source_match'] = _chk('PASS', '')
            apsl_st = to_float(_find(st, 'appraisalValue', 'appraisal_value', 'apslEvlAmt'), None)
            apsl_src = to_float(prop.get('apslEvlAmt'), None)
            if apsl_st is None:
                checks['appraisal_value'] = _chk('WARN', 'appraisalValue 필드 없음')
            elif apsl_src is None or abs(apsl_st - apsl_src) > MONEY_TOL:
                checks['appraisal_value'] = _chk('FAIL', f"전략 {apsl_st} ≠ 검색결과 {apsl_src}")
            else:
                checks['appraisal_value'] = _chk('PASS', f"{apsl_st:,.0f}")

            bid_st = to_float(_find(st, 'minBidPrice', 'currentRound.minBidPrice', 'min_bid_price', 'lowstBidPrc'), None)
            bid_src = to_float(prop.get('lowstBidPrc'), None)
            if bid_st is None:
                checks['min_bid_price'] = _chk('WARN', 'minBidPrice 필드 없음')
            elif bid_src is None or abs(bid_st - bid_src) > MONEY_TOL:
                # 다음 저감 회차를 의도적으로 채택한 경우는 rounds 에 존재하는 값이면 WARN
                round_prices = {to_float(r.get('lowstBidPrc')) for r in prop.get('rounds') or []}
                if bid_st in round_prices:
                    checks['min_bid_price'] = _chk('WARN', f"전략 {bid_st:,.0f} 는 현재 회차({bid_src:,.0f})가 아닌 "
                                                           f"다른 예약 회차 최저가 — 의도적 선택인지 확인")
                else:
                    checks['min_bid_price'] = _chk('FAIL', f"전략 {bid_st} ≠ 검색결과 {bid_src} (회차 일정에도 없음)")
            else:
                checks['min_bid_price'] = _chk('PASS', f"{bid_st:,.0f}")

        # ROI 재계산 대조 (roi_calculator.py 스키마인 경우만)
        scen = st.get('scenarios') or {}
        recomputed, mismatched = 0, []
        for name, s in scen.items():
            if not (isinstance(s, dict) and isinstance(s.get('inputs'), dict) and 'annualizedROI' in s):
                continue
            try:
                r = calc_auction(s['inputs'])
            except ROIInputError as e:
                mismatched.append(f"{name}: 재계산 불가 ({e})")
                continue
            recomputed += 1
            if abs(r['annualizedROI'] - float(s['annualizedROI'])) > ROI_TOL or \
               abs(r['netProfit'] - float(s['netProfit'])) > MONEY_TOL:
                mismatched.append(f"{name}: 저장 ROI {s['annualizedROI']}%/{s['netProfit']:,.0f} "
                                  f"≠ 재계산 {r['annualizedROI']}%/{r['netProfit']:,.0f}")
        if mismatched:
            checks['roi_recompute'] = _chk('FAIL', '; '.join(mismatched))
        elif recomputed:
            checks['roi_recompute'] = _chk('PASS', f"{recomputed}개 시나리오 재계산 일치")
        else:
            checks['roi_recompute'] = _chk('WARN', 'roi_calculator.py 스키마 아님 — 수치 재계산 불가. '
                                                   'scripts/roi_calculator.py scenarios 로 재생성 권장')

        verdict = _status(checks)
        results.append({'cltrMngNo': cid, 'file': path, 'checks': checks, 'verdict': verdict})
        if verdict == 'FAIL':
            failures.append({'cltrMngNo': cid, 'file': path,
                             'reasons': [f"{k}: {v['detail']}" for k, v in checks.items() if v['status'] == 'FAIL']})
    return {
        'verified_at': now.strftime('%Y-%m-%dT%H:%M:%S'),
        'phase': 'phase3', 'source': str(search_path), 'strategy_glob': strategy_glob,
        'checked_cltrMngNo': [r['cltrMngNo'] for r in results],
        'summary': {s: sum(1 for r in results if r['verdict'] == s) for s in ('PASS', 'WARN', 'FAIL')},
        'results': results, 'failures': failures,
    }


# ─────────────────────────── CLI ───────────────────────────
def _print_report(rep: dict):
    print(f"\n[{rep['phase']}] 검증 {len(rep['results'])}건 — "
          f"PASS {rep['summary']['PASS']} / WARN {rep['summary']['WARN']} / FAIL {rep['summary']['FAIL']}")
    for r in rep['results']:
        icon = {'PASS': '✅', 'WARN': '⚠️', 'FAIL': '❌'}[r['verdict']]
        print(f"  {icon} {r['cltrMngNo']}")
        for k, v in r['checks'].items():
            if v['status'] != 'PASS':
                print(f"      - {k}: {v['status']} {v['detail']}")


def main(argv=None):
    p = argparse.ArgumentParser(description='파이프라인 산출물 검증 (data-verifier)')
    sub = p.add_subparsers(dest='phase', required=True)
    p1 = sub.add_parser('phase1', help='검색 결과 검증')
    p1.add_argument('--input', default=str(WORKSPACE / '01_search_results.json'))
    p1.add_argument('--offline', action='store_true', help='API 재조회 없이 rounds 배열로 검증')
    p1.add_argument('--type', help='용도 필터 재지정 (기본: 결과 파일 filters.type)')
    p1.add_argument('--output', default=str(WORKSPACE / 'verification_report_phase1.json'))
    p3 = sub.add_parser('phase3', help='입찰전략 입력값·ROI 대조')
    p3.add_argument('--search', default=str(WORKSPACE / '01_search_results.json'))
    p3.add_argument('--strategy-glob', default=str(WORKSPACE / '03_bid_strategy_*.json'))
    p3.add_argument('--output', default=str(WORKSPACE / 'verification_report_phase3.json'))
    args = p.parse_args(argv)

    now = datetime.now()
    if args.phase == 'phase1':
        rep = verify_phase1(Path(args.input), args.offline, now, args.type)
    else:
        rep = verify_phase3(Path(args.search), args.strategy_glob, now)
    _print_report(rep)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n저장: {out}")
    return 1 if rep['failures'] else 0


if __name__ == '__main__':
    sys.exit(main())
