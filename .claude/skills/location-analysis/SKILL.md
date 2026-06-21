---
name: location-analysis
description: 공매 물건 주소의 입지를 분석하고 개발호재를 조사하는 스킬. 교통/인프라/시세/도시계획 분석, 개발호재 근거 조사, 투자 매력도 평가. "입지분석", "개발호재", "주변 시세", "도시계획 확인", "교통 편의", "위치 분석" 등의 요청 시 반드시 이 스킬을 사용할 것.
---

# 입지분석·개발호재 조사 스킬

## 분석 순서

### Step 1: 주소 파싱 및 행정코드 확인
- 시도/시군구/읍면동 분리
- 법정동 코드 확인 (실거래가 API에 필요)
- 카카오/네이버 지도 좌표 변환 (검색용)

### Step 2: 실거래가 조회 → **molit-market-data 스킬 사용**

아파트 물건이면 `molit-market-data` 스킬을 호출하여 매매·전월세 실거래가를 조회한다.  
필요 입력값:
- `apt_keyword`: 단지명 키워드 (예: "푸르지오1단지")
- `lawd_cd`: Step 1에서 파싱한 5자리 법정동코드
- `target_area`: 물건 전용면적 (㎡)
- `apsl_amt`: 감정가 (억 단위)

결과 파일: `_workspace/market_{cltrMngNo}.json`  
→ `summary.trade_avg`, `summary.jeonse_avg`, `summary.vs_apsl_pct` 값을 본 파일의 `market_data` 필드에 포함시킨다.

토지·상업·기타 물건이면 아래 토지 실거래가 API 직접 호출:
```python
# 토지 실거래가 조회 (아파트 아닌 경우에만)
url = "https://apis.data.go.kr/1613000/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade"
params = {'serviceKey': unquote(os.getenv('MOLIT_API_KEY')), 'LAWD_CD': lawd_cd,
          'DEAL_YMD': deal_ymd, 'numOfRows': 100, 'pageNo': 1}
```

최근 12개월치 조회 (월별 루프), 평당가 평균 계산

### Step 3: 개발호재 조사 (웹 검색)
다음 키워드로 검색:
1. `"{시군구} 도시기본계획 2030 OR 2040"`
2. `"{시군구} GTX OR 지하철 연장 확정"`
3. `"{시군구} 재개발 재건축 정비구역"`
4. `"{시군구} 산업단지 OR 물류센터 OR 복합개발"`
5. `"{시군구} 혁신도시 OR 신도시 OR 택지개발"`

각 호재에 대해:
- 유형 (교통/주거/산업/상업)
- 현황 (계획/고시/착공/준공)
- 예상 완료 시점
- 출처 (정부고시문/언론기사 URL)
- 투자 영향 (높음/중간/낮음)

### Step 4: 입지 종합 평가
점수 기준 (각 5점 만점):
- 교통: 지하철 도보 5분 이내=5, 10분=4, 버스만=2, 접근 어려움=1
- 인프라: 학군·마트·병원 풍부=5, 보통=3, 부족=1
- 개발: 확정호재 다수=5, 계획중=3, 없음=1
- 시세: 연 5% 이상 상승=5, 보합=3, 하락=1

## 토지이용계획 확인
방법 1 - 토지이음 웹사이트 안내:
1. https://www.eum.go.kr 접속
2. 주소 검색
3. 토지이용계획확인서 출력 또는 내용 확인

방법 2 - API:
- 토지특성 조회: `https://apis.data.go.kr/1611000/nsdi/LandCharacteristicsService`
- 개별공시지가: `https://apis.data.go.kr/1611000/nsdi/IndvdLandPriceService`

## 출력
`_workspace/02_location_analysis_{cltrMngNo}.json`에 저장
상세 포맷은 `location-analyst.md` 에이전트 정의 참조
