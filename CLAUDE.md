# 온비드 공매 투자 분석 하네스

**목표**: 온비드 Open API로 공매 물건을 검색·분석·입찰가 산정·최종보고서 자동 생성

**트리거**: 공매 분석, 물건 조회, 입찰 보고서, 온비드 관련 작업 요청 시 `onbid-auction-orchestrator` 스킬을 사용하라. 단순 질문은 직접 응답 가능.

## 중요 사항
- API 키: `.env` 파일의 `ONBID_API_KEY`, `MOLIT_API_KEY` (공공데이터포털 발급, 템플릿 `.env.example`)
- 스크립트는 저장소 루트 기준 상대경로로 실행 (`python3 scripts/…`). 절대경로 하드코딩 금지 — 경로·키는 `scripts/common.py`
- **수치 계산은 스크립트가 한다**: ROI/시나리오 → `scripts/roi_calculator.py`, 검색결과·전략 검증 → `scripts/verify_results.py`. LLM 은 입력 선택·해석만
- 테스트: `python3 -m pytest` (네트워크 불필요). 스크립트를 고치면 반드시 실행
- 실제 입찰은 온비드 사이트(onbid.co.kr)에서 직접 진행 (API는 조회 전용)
- 공고관리번호(pbancMngNo)가 없으면 온비드 사이트에서 먼저 검색 필요
- 중간 결과물: `_workspace/` 폴더

## 에이전트 팀
| 에이전트 | 역할 |
|---------|------|
| onbid-searcher | Open API 물건 조회·필터링 |
| document-analyzer | 감정평가서·재산명세서 PDF 분석 |
| location-analyst | 입지·개발호재·시세 분석 |
| bid-strategist | 입찰가 산정·수익성 분석 |
| report-generator | 최종 투자보고서 생성 |
| data-verifier | 검색결과(회차·용도·가격)·입찰전략(계산 입력값) 재검증. Phase 1.5, 3.5에서 호출 |

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-06-21 | 초기 구성 | 전체 | 온비드 공매 투자 분석 자동화 |
| 2026-06-21 | API 엔드포인트 수정 | onbid-searcher, onbid-search | 실제 승인 서비스는 SVC-004(OnbidRlstDtlSrvc2/getRlstDtlInf2), cltrMngNo 필수 |
| 2026-06-21 | 응답 구조 수정 | onbid-searcher, onbid-search | 응답 루트 header/body (response 래퍼 없음), 감정평가금액은 apslEvlClgList.apslEvlClg[0].apslEvlAmt |
| 2026-06-21 | molit-market-data 스킬 신규 추가 | skills/molit-market-data | 국토부 아파트 매매·전월세 실거래가 API 조회 스킬화 (RTMSDataSvcAptTradeDev + RTMSDataSvcAptRent). location-analysis Step 2에서 호출, bid-analysis 입력으로 연결 |
| 2026-07-26 | onbid-ranking-stats 스킬 신규 추가 | skills/onbid-ranking-stats, scripts/fetch_ranking_stats.py | 순위물건목록(조회수/관심물건/저감률), 부동산 물건목록, 물건 입찰결과상세, 용도별 입찰통계 6개 API 활용신청 승인. 오퍼레이션명이 docx 가이드에만 있어 실제 호출로 전부 검증 후 구현 (getInqRnkClg, getItrsCltrRnkClg, get50PctDecrCltr, getRlstCltrList2, getCltrBidRsltDtl2, getKamcoCltrUsgStats/getOrgCltrUsgStats) |
| 2026-07-26 | search_properties.py 회차선택 버그 수정 | scripts/search_properties.py, agents/data-verifier.md, skills/onbid-auction-orchestrator | 동일 cltrMngNo 다회차 dedup 시 pbctNsq(회차번호) 최댓값을 "최신"으로 오판 — 실제로는 미래 최다할인 예약회차였음. cltrBidBgngDt 최솟값(가장 이른 예정회차) 기준으로 수정. 재발 방지용 data-verifier 에이전트 신설, 오케스트레이터에 Phase 1.5/3.5 검증 단계 추가 |
| 2026-08-24 | 조기 탈락 물건도 요청 조건 필드는 전수 조회 원칙 추가 | 오케스트레이터 운영 원칙 | 신통기획 스캔에서 법정동 불일치로 조기 탈락한 4건의 연식을 "미조회"로 남겨 사용자 지적 받음. 사용자가 조건으로 명시한 필드(연식 등)는 탈락 물건도 건축물대장 표제부 API(getBrTitleInfo, ONBID 키로 호출 가능. 법정동코드는 StanReginCd API)로 채워서 보고할 것 — 탈락 사유의 완전성 확보 |
| 2026-09-02 | 결정론적 계산·검증 스크립트 도입 + 문서 정합성 정비 | scripts/roi_calculator.py, scripts/verify_results.py, scripts/common.py, scripts/search_properties.py, scripts/fetch_market_data.py, tests/, 스킬·에이전트 문서 | (1) apslRatio 버그: 상세API의 apslPrcCtrsLowstBidRto 가 null 이면 100% 로 오기록되어 90% 할인 물건이 할인 0%·점수 누락 → lowstBidPrc/apslEvlAmt 직접 계산으로 수정 (2) 회차 선택에 "종료된 회차 제외" 추가, 전체 회차 일정을 rounds 배열로 보존 (3) ROI 3시나리오·판정을 roi_calculator.py 로 코드화 (LLM 암산 금지), data-verifier 체크리스트를 verify_results.py 로 코드화 (4) fetch_market_data.py 가 타 PC 절대경로·하드코딩 물건목록이라 재사용 불가 → CLI 재작성 (5) 스킬/에이전트의 /Users/leo-myung 경로, lwstBdPrc 오타, report-generation split 버그, 목록API "미구독" 낡은 안내 정정 (6) pytest 45개, requirements.txt, .env.example, README 추가. 상세: docs/improvements/2026-09-02-fable51-review.md |
| 2026-09-02 | 후속 개선 4건: 유찰 추정 폐기, 비아파트 실거래, PDF 분석 스크립트, 취득세율 자동 | scripts/search_properties.py, fetch_market_data.py, analyze_documents.py(신규), roi_calculator.py, 스킬·에이전트 문서 | (1) 공고목록 pbancMngNo 반복 횟수를 유찰로 간주해 1단계에서 걸렀는데 실측 결과 반복 횟수는 "예약 회차 수"(359개 중 253개가 10회, 2회 등장 공고의 물건이 실제 유찰 4~6회) → 1단계 필터 제거, 단계2 usbdNft 로만 필터 (2) 국토부 오피스텔·연립다세대·단독·토지·상업용 API 7종 승인 확인 → `--kind` 로 통합, 토지·상가는 ㎡당가·면적 환산가 산출 (3) `analyze_documents.py`: pdfplumber 추출·정규식 후보값·리스크 플래그(부정문맥 구분)·스캔본 판정, LLM 은 해석 필드만 채움 (4) `roi_calculator.py tax` + `--kind`: 지방세법 §11·§13의2 기준 주택 구간/누진/중과·비주택·농지 세율을 시나리오별 입찰가에 맞춰 자동 산정. 테스트 71개 |
