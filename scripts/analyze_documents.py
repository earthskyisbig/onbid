#!/usr/bin/env python3
"""
공매 첨부서류(감정평가서·재산명세서·토지이음) PDF 분석 스크립트 (document-analysis 스킬 구현체)

    python3 scripts/analyze_documents.py --cltr-mng-no 2026-16156-004
        → _workspace/docs/2026-16156-004/*.pdf 를 모두 읽어 _workspace/02_doc_analysis_2026-16156-004.json 골격 생성
    python3 scripts/analyze_documents.py --cltr-mng-no X --pdf a.pdf b.pdf     # 경로 직접 지정
    python3 scripts/analyze_documents.py --cltr-mng-no X --dump-text            # 추출 원문을 _workspace/docs/X/_text.txt 로도 저장

스크립트가 하는 일 (결정론적):
  1. pdfplumber 로 텍스트·표 추출 (텍스트가 거의 없으면 스캔본으로 판단해 OCR 필요 표시)
  2. 정규식으로 감정평가액·기준시점·면적·공시지가·임차보증금·채권최고액·용도지역·건폐율/용적률 등 후보값 추출
  3. 키워드 기반 리스크 플래그 (유치권·법정지상권·가처분·예고등기·하자 등) — 문맥 문장을 함께 남김
  4. 신뢰도 낮은 항목은 manual_review_needed 에 기록

LLM(document-analyzer)은 이 골격을 읽고 문맥 판단이 필요한 필드(권리관계 해석, 명도 난이도, 인수금액 확정)를 채운다.
숫자는 스크립트가 뽑은 후보와 원문 문장을 대조해서 확정한다.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORKSPACE  # noqa: E402

logging.getLogger('pdfminer').setLevel(logging.ERROR)   # FontBBox 등 무해한 경고 억제

MIN_TEXT_CHARS_PER_PAGE = 40   # 이보다 적으면 스캔본(이미지 PDF)로 판단

RISK_KEYWORDS = {
    '유치권':       '⚠️ 유치권 신고 — 인수 여부·금액 확인 필요',
    '법정지상권':   '⚠️ 법정지상권 성립 가능성 — 토지/건물 소유자 분리 여부 확인',
    '가처분':       '⚠️ 가처분 등기 — 말소 여부 확인',
    '예고등기':     '⚠️ 예고등기 — 소송 결과에 따라 소유권 영향',
    '가등기':       '⚠️ 가등기 — 순위보전 목적이면 인수 위험',
    '분묘':         '⚠️ 분묘 — 분묘기지권 확인',
    '누수':         '⚠️ 건물 하자(누수) 언급',
    '하자':         '⚠️ 건물 하자 언급',
    '무단점유':     '⚠️ 무단점유 — 명도 난이도 상승',
    '대항력':       '⚠️ 대항력 있는 임차인 언급 — 보증금 인수 여부 확인',
    '체납관리비':   '⚠️ 체납관리비 언급 — 공용부분 인수 가능',
    '지분':         '⚠️ 지분 매각 가능성 — 공유자 우선매수·사용 제약 확인',
    '위반건축물':   '⚠️ 위반건축물 — 이행강제금 위험',
    '농지취득자격': '⚠️ 농지 — 농지취득자격증명 필요',
    '토지거래허가': '⚠️ 토지거래허가구역 — 허가 필요',
}

# 금액·수치 추출 패턴 (그룹1 = 값)
PATTERNS = {
    'appraisal_amount':  [r'감정평가액[^\d]{0,20}([\d,]{7,})\s*원', r'평가액\s*[:：]?\s*([\d,]{7,})\s*원',
                          r'금\s*([\d,]{7,})\s*원정?'],
    'base_date':         [r'(?:기준시점|가격시점|기준일)[^\d]{0,10}(\d{4})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})'],
    'area_sqm':          [r'(?:전용|건물|대지|토지|연)?면적[^\d]{0,15}([\d,]+\.?\d*)\s*㎡', r'([\d,]+\.?\d*)\s*㎡'],
    'gongsi_price':      [r'공시지가[^\d]{0,20}([\d,]{4,})\s*원'],
    'tenant_deposit':    [r'(?:임차)?보증금[^\d]{0,15}([\d,]{5,})\s*원'],
    'monthly_rent':      [r'월\s*(?:차임|세)[^\d]{0,15}([\d,]{4,})\s*원'],
    'max_claim':         [r'채권최고액[^\d]{0,15}([\d,]{6,})\s*원'],
    'zone':              [r'(제?\d?종?\s*(?:일반|전용|준)?\s*(?:주거|상업|공업|녹지|관리|농림|자연환경보전)지역)'],
    'bcr':               [r'건폐율[^\d]{0,10}(\d{1,3})\s*%'],
    'far':               [r'용적률[^\d]{0,10}(\d{1,4})\s*%'],
    'build_year':        [r'(?:사용승인|준공)[^\d]{0,10}(\d{4})[.\-/년]'],
    'structure':         [r'((?:철근콘크리트|철골|벽돌|목|경량철골|조적)[가-힣]*조)'],
}


# ─────────────────────────── PDF 추출 ───────────────────────────
def extract_pdf(path: Path) -> dict:
    """pdfplumber 로 페이지별 텍스트·표 추출. 반환: {pages:[str], tables:[...], scanned: bool, error}"""
    out = {'file': str(path), 'pages': [], 'tables': [], 'scanned': False, 'error': None}
    try:
        import pdfplumber
    except ImportError:
        out['error'] = 'pdfplumber 미설치 — python3 -m pip install pdfplumber'
        return out
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ''
                out['pages'].append(text)
                try:
                    for t in page.extract_tables() or []:
                        out['tables'].append(t)
                except Exception:   # 표 추출 실패는 치명적이지 않음
                    pass
    except Exception as e:
        out['error'] = f'PDF 열기 실패: {e}'
        return out
    if out['pages'] and sum(len(p.strip()) for p in out['pages']) < MIN_TEXT_CHARS_PER_PAGE * len(out['pages']):
        out['scanned'] = True
    return out


# ─────────────────────────── 텍스트 파싱 ───────────────────────────
def _to_int(s: str):
    s = s.replace(',', '').strip()
    return int(s) if s.isdigit() else None


def _to_float(s: str):
    try:
        return float(s.replace(',', ''))
    except ValueError:
        return None


def find_all(text: str, key: str) -> list:
    """PATTERNS[key] 의 모든 매치를 (값, 문맥) 튜플로. 숫자 키는 정수/실수로 변환."""
    hits = []
    for pat in PATTERNS[key]:
        for m in re.finditer(pat, text):
            ctx = text[max(0, m.start() - 30): m.end() + 30].replace('\n', ' ')
            if key == 'base_date':
                val = f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
            elif key in ('area_sqm',):
                val = _to_float(m.group(1))
            elif key in ('zone', 'structure'):
                val = re.sub(r'\s+', '', m.group(1))
            elif key in ('bcr', 'far', 'build_year'):
                val = _to_int(m.group(1))
            else:
                val = _to_int(m.group(1))
            if val is None or val == '':
                continue
            if (val, ctx) not in hits:
                hits.append((val, ctx))
        if hits and key != 'area_sqm':
            break   # 우선순위 높은 패턴에서 잡히면 다음 패턴은 보지 않는다
    return hits


def parse_appraisal(text: str) -> dict:
    amt = find_all(text, 'appraisal_amount')
    date = find_all(text, 'base_date')
    areas = find_all(text, 'area_sqm')
    gongsi = find_all(text, 'gongsi_price')
    year = find_all(text, 'build_year')
    struct = find_all(text, 'structure')
    method = None
    for m in ('거래사례비교법', '비교방식', '수익환원법', '수익방식', '원가법', '원가방식'):
        if m in text:
            method = m
            break
    return {
        'amount': max((v for v, _ in amt), default=None),           # 총액이 보통 최댓값
        'amount_candidates': [{'value': v, 'context': c} for v, c in amt[:8]],
        'base_date': date[0][0] if date else None,
        'method': method,
        'areas_sqm': sorted({v for v, _ in areas if v})[:20],
        'gongsi_price': gongsi[0][0] if gongsi else None,
        'build_year': year[0][0] if year else None,
        'structure': struct[0][0] if struct else None,
    }


def parse_property_statement(text: str) -> dict:
    deposits = find_all(text, 'tenant_deposit')
    rents = find_all(text, 'monthly_rent')
    claims = find_all(text, 'max_claim')
    has_tenant = any(k in text for k in ('임차인', '임차보증금', '전입세대', '점유자'))
    vacant = any(k in text for k in ('공실', '점유자 없음', '전입세대 없음', '임차인 없음'))
    return {
        'tenant_mentioned': has_tenant,
        'vacant_mentioned': vacant,
        'tenants': [{'deposit': v, 'context': c} for v, c in deposits[:10]],
        'monthly_rents': [{'monthly': v, 'context': c} for v, c in rents[:10]],
        'senior_claims_candidates': [{'max_claim': v, 'context': c} for v, c in claims[:10]],
        'senior_claims_sum': sum(v for v, _ in claims) if claims else None,
    }


def parse_land_use(text: str) -> dict:
    zone = find_all(text, 'zone')
    bcr = find_all(text, 'bcr')
    far = find_all(text, 'far')
    restrictions = [k for k in ('개발제한구역', '군사시설보호구역', '토지거래허가구역', '문화재보호구역',
                                '상수원보호구역', '비행안전구역', '도시계획시설', '정비구역', '재개발', '재건축',
                                '가로주택정비', '지구단위계획')
                    if k in text]
    return {
        'zone': zone[0][0] if zone else None,
        'bcr': bcr[0][0] if bcr else None,
        'far': far[0][0] if far else None,
        'restrictions': restrictions,
    }


def risk_flags(text: str) -> list[dict]:
    flags = []
    for kw, msg in RISK_KEYWORDS.items():
        idx = text.find(kw)
        if idx < 0:
            continue
        # 부정 문맥("유치권 없음", "해당 없음")은 별도 표시
        ctx = text[max(0, idx - 25): idx + 40].replace('\n', ' ')
        negated = bool(re.search(kw + r'[^\n]{0,12}(없음|없다|해당\s*없|미해당|아님)', text))
        flags.append({'keyword': kw, 'message': msg, 'negated': negated, 'context': ctx,
                      'count': text.count(kw)})
    return flags


def classify_doc(name: str, text: str) -> str:
    n = name.lower()
    if '감정' in n or '평가' in n or text.count('감정평가') >= 3:
        return 'appraisal'
    if '명세' in n or '재산' in n or '재산명세' in text:
        return 'property_statement'
    if '토지이용' in n or '토지이음' in n or '토지이용계획' in text:
        return 'land_use'
    if '등기' in n or '등기사항' in text:
        return 'registry'
    return 'unknown'


# ─────────────────────────── 조립 ───────────────────────────
def analyze(cltr_mng_no: str, pdf_paths: list[Path], dump_text: bool = False) -> dict:
    docs, all_text, manual = [], [], []
    for path in pdf_paths:
        ex = extract_pdf(path)
        text = '\n'.join(ex['pages'])
        kind = classify_doc(path.name, text)
        entry = {'file': path.name, 'kind': kind, 'pages': len(ex['pages']),
                 'chars': len(text), 'tables': len(ex['tables']), 'scanned': ex['scanned'], 'error': ex['error']}
        docs.append(entry)
        if ex['error']:
            manual.append(f"{path.name}: {ex['error']}")
            continue
        if ex['scanned']:
            manual.append(f"{path.name}: 텍스트가 거의 없음(스캔본 추정) — OCR(pytesseract) 또는 수동 확인 필요")
        all_text.append(f"\n===== {path.name} ({kind}) =====\n{text}")
        if dump_text:
            (path.parent / f"_text_{path.stem}.txt").write_text(text, encoding='utf-8')

    text = '\n'.join(all_text)
    appraisal = parse_appraisal(text) if text else {}
    statement = parse_property_statement(text) if text else {}
    land = parse_land_use(text) if text else {}
    flags = risk_flags(text) if text else []

    if not text:
        manual.append("추출된 텍스트 없음 — PDF 경로/OCR 확인")
    if appraisal and appraisal.get('amount') is None:
        manual.append("감정평가액을 찾지 못함 — 원문에서 '감정평가액' 표기 확인")
    if appraisal and len(appraisal.get('amount_candidates') or []) > 1:
        manual.append("감정평가액 후보가 여러 개 — 총액과 토지/건물 개별액 구분 확인")
    if statement.get('tenant_mentioned') and not statement.get('tenants'):
        manual.append("임차인 언급이 있으나 보증금 액수를 찾지 못함 — 임차 조건 수동 확인")
    for f in flags:
        if f['negated']:
            continue
        manual.append(f"{f['keyword']} 언급 {f['count']}회 — 문맥 확인: “{f['context'].strip()}”")

    return {
        'cltrMngNo': cltr_mng_no,
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'generator': 'scripts/analyze_documents.py',
        'documents': docs,
        'appraisal': appraisal,
        'property_statement': statement,
        'land_use': land,
        'risk_flags': flags,
        'manual_review_needed': manual,
        # LLM 이 채울 자리 (document-analyzer 출력 프로토콜)
        'rights_analysis': {'assumed_amount': None, 'basis': None},
        'eviction_risk': {'difficulty': None, 'estimated_cost': None, 'basis': None},
        'condition': {'repair_estimate': None, 'basis': None},
        'unpaid_management_fee': None,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description='공매 첨부서류 PDF 분석')
    p.add_argument('--cltr-mng-no', required=True)
    p.add_argument('--pdf', nargs='*', help='PDF 경로들 (생략 시 _workspace/docs/{id}/*.pdf)')
    p.add_argument('--dump-text', action='store_true', help='추출 원문을 txt 로 함께 저장')
    p.add_argument('--output', help='기본 _workspace/02_doc_analysis_{id}.json')
    args = p.parse_args(argv)

    if args.pdf:
        paths = [Path(x) for x in args.pdf]
    else:
        d = WORKSPACE / 'docs' / args.cltr_mng_no
        paths = sorted(d.glob('*.pdf')) if d.exists() else []
    if not paths:
        print(f"[!] PDF 없음. _workspace/docs/{args.cltr_mng_no}/ 에 저장하거나 --pdf 로 지정.\n"
              f"    다운로드: https://www.onbid.co.kr/op/cta/ctaDetail.do?cltrMngNo={args.cltr_mng_no}")
        return 1
    res = analyze(args.cltr_mng_no, paths, dump_text=args.dump_text)
    out = Path(args.output or WORKSPACE / f"02_doc_analysis_{args.cltr_mng_no}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')

    a = res['appraisal']
    print(f"\n[서류 분석] {args.cltr_mng_no} — 문서 {len(res['documents'])}건")
    for d in res['documents']:
        print(f"  - {d['file']} [{d['kind']}] {d['pages']}p {d['chars']:,}자"
              + (' ⚠️ 스캔본' if d['scanned'] else '') + (f" ❌ {d['error']}" if d['error'] else ''))
    if a:
        print(f"  감정평가액 {a.get('amount'):,}원" if a.get('amount') else "  감정평가액 미검출",
              f"| 기준시점 {a.get('base_date')} | 방법 {a.get('method')} | 준공 {a.get('build_year')}")
    print(f"  리스크 플래그 {len([f for f in res['risk_flags'] if not f['negated']])}건, 수동확인 {len(res['manual_review_needed'])}건")
    print(f"  저장: {out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
