---
name: report-generation
description: 공매 투자 분석의 모든 결과(검색/서류분석/입지분석/입찰전략)를 통합하여 최종 투자보고서를 생성하는 스킬. 마크다운 보고서, 1페이지 요약본, 입찰 체크리스트 생성. "보고서 작성", "최종 보고서", "투자보고서", "분석 결과 정리", "보고서 만들어줘", "다시 실행", "결과 업데이트" 등의 요청 시 반드시 이 스킬을 사용할 것.
---

# 최종 투자보고서 생성 스킬

## 실행 절차

### Step 1: 결과 파일 수집
```python
import json, glob, os
from datetime import datetime

workspace = '_workspace'

def load_all_results():
    search = json.load(open(f'{workspace}/01_search_results.json'))
    doc_analyses = {f.split('_')[3].replace('.json',''): json.load(open(f)) 
                    for f in glob.glob(f'{workspace}/02_doc_analysis_*.json')}
    loc_analyses = {f.split('_')[3].replace('.json',''): json.load(open(f)) 
                    for f in glob.glob(f'{workspace}/02_location_analysis_*.json')}
    strategies = {f.split('_')[3].replace('.json',''): json.load(open(f)) 
                  for f in glob.glob(f'{workspace}/03_bid_strategy_*.json')}
    return search, doc_analyses, loc_analyses, strategies
```

### Step 2: 보고서 생성 (Markdown)
물건별로 섹션 생성 후 통합

### Step 3: 파일 저장
- `_workspace/final_report_{YYYYMMDD}.md`
- `_workspace/final_report_{YYYYMMDD}_summary.md`

## 보고서 서식 표준

### 날짜/금액 표기
- 날짜: YYYY-MM-DD HH:MM
- 금액: 한국식 (억/만원) + 괄호 안에 원 단위 (예: 3억 287만원 (302,872,850원))
- 비율: X.X% 형식

### 투자 결정 뱃지
- 입찰 강력 권고: ROI 20% 이상
- 입찰 권고: ROI 15-20%
- 조건부 입찰: ROI 10-15% (특정 조건 충족 시)
- 입찰 보류: ROI 10% 미만 또는 고리스크
- 입찰 포기: 선순위 채권 과다, 명도 불가 등 구조적 문제

### 요약본 (1페이지) 필수 항목
1. 물건 기본정보 (3줄)
2. 입찰 마감일시
3. 권고 입찰가 및 근거
4. 예상 수익 (기준 시나리오)
5. 최대 리스크 1개
6. 투자 판단 (한 줄)
7. 즉시 해야 할 행동 (체크리스트)

## 입찰 주의사항 (보고서 필수 포함)
⚠️ 실제 입찰은 온비드(onbid.co.kr)에서 직접 진행해야 합니다.
⚠️ 이 보고서는 투자 판단 참고용이며, 법적/세무적 검토는 전문가와 별도 확인 필요.
⚠️ 낙찰 후 계약 해제 불가 — 입찰 전 반드시 현장 답사 권장.
⚠️ 입찰 보증금(최저입찰가의 10%)은 낙찰 불성립 시 환불, 포기 시 몰수.
