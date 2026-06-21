---
name: onbid-auction-orchestrator
description: 온비드 공매 투자 전체 워크플로우를 조율하는 오케스트레이터. 물건 검색→서류분석→입지분석→입찰가산정→최종보고서 순서로 에이전트 팀을 지휘. "공매 분석해줘", "온비드 물건 분석", "입찰 보고서", "공매 투자 검토", "물건 찾아서 분석", "다시 분석", "재실행", "업데이트" 등의 요청 시 반드시 이 스킬을 사용할 것.
---

# 온비드 공매 투자 오케스트레이터

## 실행 모드: 하이브리드
- Phase 1 (검색): 서브에이전트 단독
- Phase 2 (분석): 에이전트 팀 병렬 (document-analyzer + location-analyst)
- Phase 3 (전략): 서브에이전트 단독
- Phase 4 (보고서): 서브에이전트 단독

## Phase 0: 컨텍스트 확인

`_workspace/` 존재 여부 확인:
- 없음 → **초기 실행**: Phase 1부터 전체 실행
- 있고 `01_search_results.json` 있음 + 부분 수정 요청 → **부분 재실행**: 해당 에이전트만 재호출
- 있고 사용자가 새 공고번호 제공 → **새 실행**: 기존 `_workspace`를 `_workspace_prev_{타임스탬프}/`로 이동 후 재시작

체크리스트 - 사용자에게 확인할 사항:
1. 공고관리번호 목록 (pbancMngNo) - 없으면 온비드 사이트 안내
2. PDF 첨부서류 경로 (없으면 API 데이터만으로 진행)
3. 투자 조건 (목표 수익률, 최대 투자금, 선호 지역)
4. .env 파일의 ONBID_API_KEY 설정 여부

## Phase 1: 물건 검색·필터링
**실행 모드**: 서브에이전트 (onbid-searcher)

```
Agent(
  name: "onbid-searcher",
  subagent_type: "general-purpose",
  model: "opus",
  prompt: """
  onbid-search 스킬을 사용하여 다음 공고관리번호의 물건을 조회하라:
  {pbancMngNo_list}
  
  필터 조건:
  - 재산유형: {property_type}
  - 최대 최저입찰가: {max_price}
  - 대상 지역: {region}
  
  결과를 _workspace/01_search_results.json에 저장하라.
  """
)
```

**완료 조건**: `_workspace/01_search_results.json` 생성, 최소 1개 물건 포함

## Phase 2: 병렬 서류분석 + 입지분석
**실행 모드**: 에이전트 팀 (parallel)

각 물건(Phase 1 결과에서 상위 3개 또는 사용자 지정)에 대해:

```
# document-analyzer 서브에이전트 (각 물건별, run_in_background=true)
Agent(
  name: "document-analyzer-{cltrMngNo}",
  subagent_type: "general-purpose", 
  model: "opus",
  run_in_background: true,
  prompt: """
  document-analysis 스킬을 사용하여 다음 물건의 첨부서류를 분석하라:
  cltrMngNo: {cltrMngNo}
  PDF 경로: _workspace/docs/{cltrMngNo}/
  
  결과를 _workspace/02_doc_analysis_{cltrMngNo}.json에 저장하라.
  PDF가 없으면 온비드 URL 안내 후 API 데이터만으로 가능한 분석 수행.
  """
)

# location-analyst 서브에이전트 (각 물건별, run_in_background=true)
Agent(
  name: "location-analyst-{cltrMngNo}",
  subagent_type: "general-purpose",
  model: "opus", 
  run_in_background: true,
  prompt: """
  location-analysis 스킬을 사용하여 다음 물건의 입지를 분석하라:
  주소: {cltrAdr}
  물건유형: {prptDivNm}
  cltrMngNo: {cltrMngNo}
  
  결과를 _workspace/02_location_analysis_{cltrMngNo}.json에 저장하라.
  """
)
```

두 에이전트를 같은 메시지에서 동시에 호출하여 병렬 실행.
**완료 조건**: 모든 `02_*.json` 파일 생성

## Phase 3: 입찰가 산정·수익성 분석
**실행 모드**: 서브에이전트 (bid-strategist)

```
Agent(
  name: "bid-strategist",
  subagent_type: "general-purpose",
  model: "opus",
  prompt: """
  bid-analysis 스킬을 사용하여 각 물건의 입찰가와 수익성을 분석하라.
  
  입력 파일:
  - _workspace/01_search_results.json
  - _workspace/02_doc_analysis_*.json (각 물건별)
  - _workspace/02_location_analysis_*.json (각 물건별)
  
  투자자 목표: {investor_goal}
  
  각 물건별 결과를 _workspace/03_bid_strategy_{cltrMngNo}.json에 저장하라.
  """
)
```

## Phase 4: 최종 보고서 생성
**실행 모드**: 서브에이전트 (report-generator)

```
Agent(
  name: "report-generator",
  subagent_type: "general-purpose",
  model: "opus",
  prompt: """
  report-generation 스킬을 사용하여 최종 투자보고서를 생성하라.
  
  입력 파일: _workspace/ 아래 모든 JSON 파일
  
  출력:
  - _workspace/final_report_{날짜}.md
  - _workspace/final_report_{날짜}_summary.md
  """
)
```

## 데이터 흐름
```
사용자 입력 (공고번호, 조건, PDF)
    ↓
_workspace/01_search_results.json
    ↓ (분기: 물건별 병렬)
_workspace/02_doc_analysis_{id}.json     }
_workspace/02_location_analysis_{id}.json } → 병렬 생성
    ↓
_workspace/03_bid_strategy_{id}.json
    ↓
_workspace/final_report_{날짜}.md
_workspace/final_report_{날짜}_summary.md
```

## 에러 핸들링
| 상황 | 처리 |
|------|------|
| API 키 없음 | .env 파일 설정 안내, 진행 중단 |
| 공고번호 없음 | 온비드 사이트 검색 방법 안내 |
| PDF 없음 | API 데이터만으로 진행, 보고서에 "서류 미분석" 표기 |
| 분석 실패 1건 | 해당 물건 스킵, 보고서에 이유 명시 |
| 모든 분석 실패 | 사용자에게 에러 보고 후 중단 |

## 테스트 시나리오

### 정상 흐름
```
입력: pbancMngNo=["202406-21411-00"]
      region="경기도", max_price=500000000
예상: search_results.json → doc/location analysis → bid strategy → 최종보고서
```

### 에러 흐름 (API 키 미설정)
```
입력: pbancMngNo=["202406-21411-00"]
      .env에 ONBID_API_KEY 없음
예상: Phase 1에서 에러 감지 → 설정 안내 메시지 → 중단
```

## API 레퍼런스
`references/api-spec.md` — 전체 응답 필드 정의
`references/code-tables.md` — 재산유형/처분방식/입찰결과 코드표
