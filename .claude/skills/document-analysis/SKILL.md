---
name: document-analysis
description: 공매 물건의 감정평가서, 재산명세서, 토지이음 자료 등 PDF 첨부서류를 분석하는 스킬. PDF 텍스트·표 추출, 권리관계 분석, 임차인 현황 파악, 핵심 투자 정보 구조화. "감정평가서 분석", "재산명세서 확인", "첨부서류 검토", "PDF 분석", "권리관계 확인" 등의 요청 시 반드시 이 스킬을 사용할 것.
---

# 공매 첨부서류 분석 스킬

## 구현체 (먼저 실행)
```bash
python3 scripts/analyze_documents.py --cltr-mng-no {cltrMngNo}            # _workspace/docs/{id}/*.pdf → 02_doc_analysis_{id}.json 골격
python3 scripts/analyze_documents.py --cltr-mng-no {id} --pdf a.pdf b.pdf --dump-text
```
스크립트가 텍스트·표 추출, 감정평가액/기준시점/면적/공시지가/보증금/채권최고액/용도지역/건폐율·용적률 후보 추출,
리스크 키워드 플래그(부정 문맥 "없음" 구분), 스캔본 판정, `manual_review_needed` 목록까지 만든다.
LLM 은 그 JSON 을 읽고 **비어 있는 해석 필드**(`rights_analysis.assumed_amount`, `eviction_risk`, `condition.repair_estimate`,
`unpaid_management_fee`)를 원문 문맥(`*_candidates[].context`)을 근거로 채운다. 숫자 후보를 고를 때는 문맥을 인용한다.
스캔본(`documents[].scanned=true`)이면 `pip install pytesseract pillow` 후 OCR 을 시도하거나 수동 확인으로 표기.

환경: `pdfplumber` (requirements.txt). PyMuPDF 는 선택.

## 분석 절차 (스크립트가 수행 — 참고용 명세)

### Step 1: PDF 파일 위치 확인
PDF 파일 경로: `_workspace/docs/{cltrMngNo}/`

파일이 없으면:
1. 온비드 사이트에서 다운로드: `https://www.onbid.co.kr/op/cta/ctaDetail.do?cltrMngNo={cltrMngNo}`
2. `_workspace/docs/{cltrMngNo}/` 폴더에 저장 요청

### Step 2: PDF 텍스트 추출
```python
import pdfplumber, json

def extract_pdf_content(pdf_path):
    full_text = ""
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            full_text += text + "\n"
            page_tables = page.extract_tables() or []
            tables.extend(page_tables)
    return {"text": full_text, "tables": tables}
```

### Step 3: 감정평가서 핵심 항목 파싱
찾아야 할 패턴:
- 감정평가액: `r'감정평가액.*?([0-9,]+)\s*원'`
- 기준일: `r'기준시점.*?(\d{4})[년.]\s*(\d{1,2})[월.]\s*(\d{1,2})'`
- 면적: `r'([0-9.]+)\s*㎡'`
- 공시지가: `r'공시지가.*?([0-9,]+)\s*원'`

### Step 4: 재산명세서 핵심 항목 파싱
찾아야 할 패턴:
- 임차인: `r'임차인|임차보증금|전세|월세'`
- 선순위채권: `r'근저당|저당권|채권최고액.*?([0-9,]+)원'`
- 유치권: `r'유치권'` (존재 여부)
- 법정지상권: `r'법정지상권'` (존재 여부)

### Step 5: 리스크 플래그 생성
```python
def generate_risk_flags(text):
    flags = []
    if '유치권' in text: flags.append("⚠️ 유치권 신고 확인 필요")
    if '법정지상권' in text: flags.append("⚠️ 법정지상권 확인 필요")
    if '가처분' in text: flags.append("⚠️ 가처분 등기 확인 필요")
    if '예고등기' in text: flags.append("⚠️ 예고등기 확인 필요")
    if '누수' in text or '하자' in text: flags.append("⚠️ 건물 하자 확인 필요")
    return flags
```

## 토지이음 자료 처리
토지이음(eum.go.kr) 자료가 있으면:
- 용도지역 (제1종 일반주거/상업/녹지 등)
- 건폐율/용적률
- 도시계획시설 저촉 여부
- 행위제한 사항

API 방식이면 `LAND_USE_API_KEY`로 호출:
- URL: `https://apis.data.go.kr/1611000/nsdi/LandUseInformService`

## 출력
`_workspace/02_doc_analysis_{cltrMngNo}.json`에 구조화 저장
상세 포맷은 `document-analyzer.md` 에이전트 정의 참조
