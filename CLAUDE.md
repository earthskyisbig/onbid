# 온비드 공매 투자 분석 하네스

**목표**: 온비드 Open API로 공매 물건을 검색·분석·입찰가 산정·최종보고서 자동 생성

**트리거**: 공매 분석, 물건 조회, 입찰 보고서, 온비드 관련 작업 요청 시 `onbid-auction-orchestrator` 스킬을 사용하라. 단순 질문은 직접 응답 가능.

## 중요 사항
- API 키: `.env` 파일의 `ONBID_API_KEY` (공공데이터포털 발급)
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

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-06-21 | 초기 구성 | 전체 | 온비드 공매 투자 분석 자동화 |
| 2026-06-21 | API 엔드포인트 수정 | onbid-searcher, onbid-search | 실제 승인 서비스는 SVC-004(OnbidRlstDtlSrvc2/getRlstDtlInf2), cltrMngNo 필수 |
| 2026-06-21 | 응답 구조 수정 | onbid-searcher, onbid-search | 응답 루트 header/body (response 래퍼 없음), 감정평가금액은 apslEvlClgList.apslEvlClg[0].apslEvlAmt |
| 2026-06-21 | molit-market-data 스킬 신규 추가 | skills/molit-market-data | 국토부 아파트 매매·전월세 실거래가 API 조회 스킬화 (RTMSDataSvcAptTradeDev + RTMSDataSvcAptRent). location-analysis Step 2에서 호출, bid-analysis 입력으로 연결 |
