# 온비드 공매 투자 분석 하네스

온비드(OnBid) Open API 로 공매 물건을 검색하고, 국토부 실거래가·네이버 호가로 시세를 검증한 뒤,
입찰가 시나리오와 최종 투자보고서까지 Claude Code 에이전트 팀이 자동 생성하는 프로젝트다.

**운영 규칙(요약)**: 숫자는 스크립트가 만들고 LLM 은 고르고 해석한다. 검색 결과와 입찰전략은 검증 스크립트를 통과해야 보고서로 간다.

## 설치

```bash
cp .env.example .env            # ONBID_API_KEY, MOLIT_API_KEY 입력 (공공데이터포털)
python3 -m pip install -r requirements.txt   # Homebrew Python 은 --user 또는 venv
python3 -m pytest                # 71개 테스트, 네트워크 불필요
```

## 파이프라인

```
Phase 1   scripts/search_properties.py      → _workspace/01_search_results.json
Phase 1.5 scripts/verify_results.py phase1  → verification_report_phase1.json   (회차·가격·용도)
Phase 2   scripts/analyze_documents.py + location-analysis (fetch_market_data.py --kind …, fetch_naver_listings.py)
Phase 3   scripts/roi_calculator.py scenarios → 03_bid_strategy_{id}.json      (보수/기준/공격 + 판정)
Phase 3.5 scripts/verify_results.py phase3  → verification_report_phase3.json   (원본 대조 + ROI 재계산)
Phase 4   report-generation                 → final_report_{날짜}.md
```

오케스트레이션 정의: `.claude/skills/onbid-auction-orchestrator/SKILL.md`. Claude Code 에서 "공매 분석해줘" 로 트리거된다.

## 스크립트

| 스크립트 | 용도 | 예시 |
|---------|------|------|
| `search_properties.py` | 물건 검색 (필터 또는 `--ids`) | `python3 scripts/search_properties.py --region "경기도 수원시" --type 아파트 --min-fails 2` |
| `verify_results.py` | 검색결과/전략 검증 (종료코드 1 = FAIL) | `python3 scripts/verify_results.py phase1` |
| `roi_calculator.py` | 경매 ROI / 갭투자 ROE / 3시나리오 / 취득세율 | `python3 scripts/roi_calculator.py scenarios --appraisal 2.5e8 --min-bid 2e8 --fair-value 2.55e8 --kind house --area-sqm 59` |
| `fetch_market_data.py` | 국토부 실거래가 (`--kind apt\|offi\|rh\|sh\|land\|shop`) | `python3 scripts/fetch_market_data.py --kind rh --keyword 호안빌 --lawd-cd "서울 은평구" --area 39.94` |
| `analyze_documents.py` | 감정평가서·재산명세서 PDF 분석 골격 | `python3 scripts/analyze_documents.py --cltr-mng-no 2026-16156-004` |
| `fetch_naver_listings.py` | 네이버 부동산 호가 | `python3 scripts/fetch_naver_listings.py --keyword 일신 --lawd-cd 41650 --area 49.92` |
| `fetch_ranking_stats.py` | 조회수/관심/저감률 순위, 입찰결과, 용도별 통계 | `python3 scripts/fetch_ranking_stats.py discount-rank --cltr-div 부동산` |
| `common.py` | 경로·키·API 호출·응답 파싱 공통 | (라이브러리) |

모든 금액 인자는 **원 단위**, 비율은 소수(`0.011` = 1.1%). 저장소 루트에서 실행하면 `.env` 를 자동 로드한다.

## 알아둘 것

- **회차 선택**: 온비드 압류재산은 미래 회차를 미리 예약해 둔다. 현재 회차 = 종료되지 않은 회차 중 입찰시작일이 가장 이른 회차. `pbctNsq` 최댓값을 쓰면 존재하지 않는 미래 최저가로 계산하게 된다 (2026-07-26 사고).
- **감정가 대비 비율**: API 필드가 null 로 오는 경우가 많아 `lowstBidPrc / apslEvlAmt` 로 직접 계산한다 (2026-09-02 수정).
- **유찰횟수**: 공고목록의 반복 횟수는 예약 회차 수다. 유찰 필터는 물건별 `usbdNft` 로만 건다 (2026-09-02 실측 후 수정).
- 실제 입찰은 onbid.co.kr 에서 직접. API 는 조회 전용.
- 중간 산출물 `_workspace/` 는 git 추적 제외.

## 문서

- `CLAUDE.md` — 에이전트 팀·변경 이력
- `docs/improvements/` — 코드·문서 점검 및 개선 기록
- `docs/worklog/` — 세션별 작업 로그
- `docs/prompt-guide.md` — Claude Code 프롬프트 가이드
