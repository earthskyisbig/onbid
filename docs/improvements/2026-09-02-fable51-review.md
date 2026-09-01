# 워크스페이스 점검·개선 기록 — 2026-09-02

> 작성: Claude Fable 5.1. 요청: "이 워크스페이스에서 개선 가능한 부분을 찾아 최대한 개선하고 무엇을 했는지 파일로 남겨라."
> 범위: `scripts/`, `.claude/skills`, `.claude/agents`, `CLAUDE.md`, 저장소 구성. `_workspace/`(산출물)와 `docs/superpowers/`(과거 계획 문서)는 손대지 않음.

## 0. 한 줄 요약

이 하네스의 가장 큰 약점은 **"숫자를 LLM 이 만든다"** 는 구조였다. 검색 스크립트는 API 가 비워 보낸 비율 필드를 100% 로 기록했고, ROI 3시나리오는 스킬 문서만 있고 계산 코드가 없었으며, 검증 에이전트도 체크리스트를 눈으로 대조하는 방식이었다. 오늘 이 세 지점을 전부 코드로 옮기고(계산기·검증기·테스트 45개), 재사용 불가능하던 스크립트 2개를 CLI 로 고치고, 문서와 코드가 어긋난 곳 9군데를 맞췄다.

## 1. 발견한 문제 (심각도 순)

| # | 심각도 | 위치 | 문제 | 영향 |
|---|-------|------|------|------|
| 1 | **높음 (실제 버그)** | `scripts/search_properties.py` `normalize_item` | 상세 API 의 `apslPrcCtrsLowstBidRto` 가 `null` 이면 `or 100` 으로 **100%** 기록. 실측: 은평구 다세대(감정가 4.24억, 최저가 4,240만 = 10%)가 `apslRatio=100`, `priority_score=50` 으로 저장됨 | 90% 할인 물건이 "할인 0%" 로 보임. 우선순위 30점 누락. 8/23 전략 문서에도 "apslRatio 신뢰 불가" 메모가 남아 있었으나 코드는 미수정 |
| 2 | **높음 (구조)** | `.claude/skills/roi-calculator`, `bid-analysis` | 공식·시나리오·판정 규칙이 문서로만 존재. 계산은 매번 LLM 암산 | 8/23 전략 파일은 스킬 스키마와 다른 임의 구조(aggressive/neutral…)로 생성됨 → data-verifier 가 대조할 기준이 없음 |
| 3 | **높음 (구조)** | `.claude/agents/data-verifier.md` | 검증 체크리스트가 전부 수동. API 재조회·원 단위 대조를 에이전트가 손으로 함 | 검증이 느리고 재현 불가. 7/26 사고 재발을 막는 장치가 사람 눈에 의존 |
| 4 | 중간 | `scripts/search_properties.py` 회차 선택 | 종료된 회차를 후보에서 빼지 않음 (API 가 만료 회차를 돌려주면 과거 회차 채택). `--rows` 인자가 선언만 되고 미사용, 상세조회 `numOfRows=10` 고정 | 회차가 10개 넘는 물건은 일정이 잘릴 수 있음 |
| 5 | 중간 | `scripts/search_properties.py` `apply_filters` | 정규화 여부를 두 번 검사하는 죽은 코드, `price_min=0`·`area_min=0` 이 "없음" 으로 처리되는 truthiness 버그 | 가독성·엣지케이스 |
| 6 | **높음 (재사용 불가)** | `scripts/fetch_market_data.py` | 다른 PC 절대경로 `/Users/leo-myung/onbid/.env` 하드코딩(이 PC 에서 401), 물건 8건이 코드에 하드코딩, 출력 파일명 `market_data_20260621.json` 고정, API 오류코드 미검사 | 스킬은 "스크립트 있음" 이라 안내하지만 실제로는 6/21 일회용. 스킬 문서에 같은 코드를 인라인으로 중복 |
| 7 | 중간 | `scripts/fetch_naver_listings.py` | `.env`·출력 경로 절대경로 하드코딩 | 이 PC 에서 `.env` 미로드 |
| 8 | 중간 | 스킬·에이전트 6개 파일 | `python3 /Users/leo-myung/onbid/scripts/...` 경로 11곳 | 에이전트가 그대로 실행하면 실패 |
| 9 | 중간 | `.claude/skills/bid-analysis` | 최저입찰가 필드명 `lwstBdPrc` (실제 `lowstBidPrc`), `load_analysis_data` 의 `or p.get('pbancMngNo')` 가 항상 첫 물건을 반환 | 잘못된 물건 매칭 가능 |
| 10 | 중간 | `.claude/skills/report-generation` | `f.split('_')[3]` 로 cltrMngNo 추출 → 경로 `_workspace/02_doc_analysis_X.json` 에서는 `'analysis'` 가 나옴 | 보고서 스킬 코드가 동작하지 않음 |
| 11 | 낮음 | `onbid-search` SKILL, `onbid-searcher` 에이전트 | "목록 API 별도 구독 필요 / 403" 안내가 낡음(이미 승인·동작). 응답 루트 "`result` 키" 오기 | 에이전트가 필터 검색을 포기하고 `--ids` 만 쓰게 유도 |
| 12 | 낮음 | `.claude/agents/bid-strategist.md` | 출력 스키마(optimistic/base/conservative, recommended_bid…)가 bid-analysis 스킬 스키마와 불일치. 자체 ROI 공식 템플릿 보유 | 어느 스키마를 따를지 에이전트마다 다름 |
| 13 | 낮음 | 저장소 | `requirements.txt`, `.env.example`, `README.md`, 테스트 없음. `CLAUDE.md` 변경 이력 날짜 순서 뒤섞임 | 새 PC·새 세션 온보딩 비용 |
| 14 | 낮음 | `api-spec.md` | 구버전 `OnbidPbancCltrDtlSrvc/getPbancCltrInf` 만 기술, 코드는 `Srvc2` 사용 | 혼동 |

## 2. 적용한 개선

### 2.1 새 스크립트
| 파일 | 내용 |
|------|------|
| `scripts/common.py` | 저장소 루트/워크스페이스 경로, `.env` 로드, `get_key`(unquote), `onbid_get`(429·타임아웃 재시도), `parse_onbid_response`(header/body·result 양쪽), `format_price` |
| `scripts/roi_calculator.py` | `auction` / `gap` / `scenarios` 서브커맨드. references 의 공식을 그대로 구현. `scenarios` 는 bid-analysis 의 보수/기준/공격 표, 판정(≥15/10~15/<10), 권고가 `min(공격 bid, fair×0.85, 구간상한)`, 리스크 기대비용까지 산출해 `03_bid_strategy_{id}.json` 골격을 만든다. fair×0.85 가 최저가보다 낮으면 자동 보류 + 경고. 입력 검증 실패는 종료코드 2 |
| `scripts/verify_results.py` | data-verifier 체크리스트 1~4 구현. `phase1`: 회차 재조회(또는 `--offline` 으로 `rounds` 배열) 후 기대 회차·만료 여부·최저가 대조, 최저가≤감정가, 저장된 apslRatio 와 직접계산 대조, 용도 소분류 일치. `phase3`: 전략 파일의 감정가·최저가를 원 단위로 대조(다른 예약 회차 값이면 WARN), 시나리오 ROI 를 재계산해 ±0.05%p 대조. FAIL 있으면 종료코드 1 |

### 2.2 수정한 스크립트
| 파일 | 변경 |
|------|------|
| `scripts/search_properties.py` | `apslRatio` 를 `lowstBidPrc/apslEvlAmt` 직접 계산(API 값은 `apslRatio_api` 보존), `discount_pct` 추가. 회차 선택을 `select_current_round` 로 분리: 종료된 회차 제외 → 가장 이른 시작일. 전체 회차 일정 `rounds`·`round_count`·`bid_window`(open/upcoming/ended)·`days_to_bid_end` 출력. `--rows` 를 상세조회에 실제 적용(기본 100). 죽은 코드 제거, `is not None` 비교, `common.py` 사용. CLI 인터페이스는 그대로 |
| `scripts/fetch_market_data.py` | 전면 재작성: `--keyword/--lawd-cd/--area/--apsl/--low-bid/--months/--area-tol/--batch` CLI. 지역명→LAWD_CD 표(경기 전역+서울 25구), XML resultCode 검사, 계약해제(`cdealType=O`) 제외, 0건 시 ±10㎡→24개월 자동 확장(스킬 Step 3 규칙), 중앙값·최근거래일·전세가율·유동성 플래그 |
| `scripts/fetch_naver_listings.py` | 경로만 저장소 상대경로로 (로직 불변) |
| `scripts/fetch_ranking_stats.py` | `common.py` 사용 (로직 불변) |

### 2.3 테스트 (`tests/`, 45개, 네트워크 불필요, `python3 -m pytest`)
- `test_roi_calculator.py`: references 의 예제값(경매 3.4%, 갭 ROE 15.0%/연 7.5%/역전세 −18.3%) 정확 일치, 경고 조건 전부, 검증 오류 6종, 시나리오 판정 3분기, CLI/`--json-in`/종료코드
- `test_search_properties.py`: **7/26 회차 버그 회귀 테스트**(pbctNsq 최댓값 아닌 가장 이른 회차), 만료 회차 제외, 비율 직접 계산 우선, 점수, 필터(빈 `--type` 회귀 포함), 다회차 dedup
- `test_market_and_naver.py`: XML 정상/오류/깨짐, 만원→원, 월 경계, 집계·플래그, 네이버 가격 파서, 온비드 응답 파서 변형, 금액 포맷
- `test_verify_results.py`: phase1 PASS/잘못된 회차/만료/비율 오염/용도 혼입, phase3 정상 일치/ROI 조작·감정가 불일치·다른 회차 WARN/구 스키마 WARN

### 2.4 실제 API 로 확인한 것
- `search_properties.py --ids 2024-18146-006 2026-16156-004`: 은평 다세대 `apslRatio 100→10.0`, `priority_score 50→80`, 회차 10건 보존. 금천 오피스텔은 0% 할인·036회차 그대로 (정상)
- `verify_results.py phase1`(온라인) 2건 PASS, `phase3` 는 8/23 구 스키마 파일에 대해 "재계산 불가" WARN (의도된 동작)
- `fetch_market_data.py --keyword 은마 --lawd-cd 11680 --area 76.79 --months 3`: 매매 5건·전세 18건 정상 수신. 메트로타운(오피스텔)은 아파트 API 대상이 아니라 0건 + 유동성 경고 (정상)
- `fetch_ranking_stats.py discount-rank`: 정상

### 2.5 문서 정합성
| 파일 | 변경 |
|------|------|
| `onbid-search/SKILL.md` | 전면 갱신: 3단계 API 전부 승인 상태로 정정, 회차 선택 절대 규칙, 실제 출력 스키마(`apslRatio` 직접계산·`rounds`), 검증 스크립트 필수 단계 |
| `bid-analysis/SKILL.md` | 전면 갱신: 계산은 `roi_calculator.py scenarios` 1회 호출, 입력값 출처 표(필드명 `lowstBidPrc` 로 정정, `load_analysis_data` 버그 수정), 취득세율 표, LLM 은 해석 필드만 추가, 출력 스키마 = 스크립트 스키마 |
| `molit-market-data/SKILL.md` | 인라인 코드 제거 → CLI 사용법, 단지명 키워드 잡는 법, 출력 스키마, 단위 원으로 통일 |
| `roi-calculator/SKILL.md` | 상단에 구현체 사용법 삽입 ("수식을 손으로 계산하지 않는다") |
| `report-generation/SKILL.md` | `split('_')[3]` → 정규식 추출, 검증 보고서 로드, "숫자는 전략 파일에서 그대로 옮긴다" 원칙 |
| `onbid-auction-orchestrator/SKILL.md` | Phase 1.5/3/3.5 프롬프트를 스크립트 실행 기반으로, 스크립트·테스트 표 추가 |
| `agents/bid-strategist.md` | 전면 갱신: 스크립트 호출 절차, 수치 수정 금지, 회차는 `rounds` 만 사용 |
| `agents/data-verifier.md` | "먼저 `verify_results.py` 실행" 절, 출력 스키마 갱신 |
| `agents/onbid-searcher.md` | 응답 루트 오기 정정, 목록 API 안내 갱신, 출력 스키마 갱신, numOfRows≥100 |
| `agents/location-analyst.md`, `location-analysis`, `naver-land-data` | 절대경로 → `scripts/` |
| `references/api-spec.md` | Srvc2 엔드포인트 사용 주석 |
| `CLAUDE.md` | 중요 사항 4줄 추가(상대경로·스크립트 계산·테스트), 변경 이력 날짜순 정렬 + 오늘 행 |
| 신규 | `README.md`, `requirements.txt`, `.env.example`, `pytest.ini` |

## 3. 하지 않은 것 / 다음에 할 것

| 항목 | 이유·제안 |
|------|----------|
| `_workspace/03_bid_strategy_2026-16156-004.json` 재생성 | 8/23 분석 산출물은 기록이므로 손대지 않음. 다음 실행부터 새 스키마 적용 |
| 네이버 호가 실호출 검증 | 봇 차단 리스크로 파서 단위테스트만. 로직 불변 |
| 모드 B(필터 검색) 실호출 | 공고 100건 ≈ 2~3분 소요라 세션에서 생략. 회차 선택·사전필터 로직은 모드 A 와 같은 함수를 쓰므로 단위테스트로 커버 |
| 유찰횟수 추정 방식 | 목록 API 에서 `pbancMngNo` 반복 횟수로 유찰을 추정하는데, 상세 API 의 `usbdNft` 가 더 정확. 모드 B 단계1 필터를 느슨하게(threshold−1) 두고 단계3 에서 `usbdNft` 로 확정하는 편이 누락이 적다 — 실데이터로 반복 패턴을 검증한 뒤 변경 권장 |
| 토지·상가 실거래 API | `location-analysis` 가 `RTMSDataSvcLandTrade` 를 인라인 코드로만 안내. `fetch_market_data.py` 에 `--kind land\|shop` 서브모드 추가하면 비주택 물건도 같은 스키마로 시세 확보 가능 |
| `document-analysis` 스크립트화 | PDF 추출·리스크 플래그가 문서 내 코드 조각. `scripts/analyze_documents.py` 로 옮기면 `02_doc_analysis` 도 결정론적 골격을 가질 수 있음 |
| 취득세율 자동 결정 | 현재 표 참고 후 수동 지정. 주택 여부·가격·보유주택수를 인자로 받아 세율을 내는 함수를 `roi_calculator.py` 에 추가하면 실수 감소 |
| `docs/superpowers/plans/2026-06-25-*.md` 의 절대경로 | 과거 계획 문서라 그대로 둠 |
| 커밋 | 요청에 없어 커밋하지 않음. `git status` 로 확인 후 커밋 권장 |

## 4. 재현 (다음 세션에서 확인하는 법)

```bash
python3 -m pytest                                              # 45 passed
python3 scripts/roi_calculator.py auction --appraisal 425000000 --bid 382500000 --sale 409000000 --months 6   # 연환산 3.4%
python3 scripts/search_properties.py --ids 2024-18146-006 --output /tmp/s.json && python3 scripts/verify_results.py phase1 --input /tmp/s.json --offline
```
