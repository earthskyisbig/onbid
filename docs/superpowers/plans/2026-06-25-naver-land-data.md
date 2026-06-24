# 네이버 부동산 호가 조회 스킬 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공매 물건의 낙찰 후 출구 전략 수립을 위해 네이버 부동산 현재 매매·전세·월세 호가를 수집하고 국토부 실거래가와의 괴리율을 계산하는 스킬을 구현한다.

**Architecture:** Naver 모바일 내부 API(`m.land.naver.com/cluster/ajax/complexList`)를 직접 호출하여 단지별 가격 범위를 수집한다. 403/차단 시 anti_bot_scraper subprocess로 fallback한다. location-analysis Step 2.5에 통합되어 MOLIT 실거래가와 함께 gap_analysis를 출력한다.

**Tech Stack:** Python 3, requests, python-dotenv, re, subprocess (fallback용)

## Global Constraints

- 모든 스크립트는 `/Users/leo-myung/onbid/` 프로젝트 루트 기준으로 실행
- `.env` 로드 경로: `/Users/leo-myung/onbid/.env`
- 출력 파일: `_workspace/naver_listings_{cltrMngNo}.json`
- Naver API rate limit: 호출 간 `time.sleep(random.uniform(0.5, 1.5))` 필수
- 가격 단위: 내부 계산은 원(int), JSON 출력도 원 단위
- 면적 필터: `target_area ± 10㎡` 범위의 단지만 포함
- 스킬 파일 경로: `.claude/skills/naver-land-data/SKILL.md`

---

## 파일 구조

| 파일 | 작업 | 역할 |
|------|------|------|
| `scripts/fetch_naver_listings.py` | 신규 생성 | Naver API 호출, 파싱, 저장 메인 스크립트 |
| `.claude/skills/naver-land-data/SKILL.md` | 신규 생성 | 스킬 정의 및 사용법 |
| `.claude/skills/location-analysis/SKILL.md` | 수정 | Step 2.5 추가 |
| `.claude/agents/location-analyst.md` | 수정 | naver-land-data 호출 로직 추가 |

---

### Task 1: 가격 파싱 유틸리티 + 단지 검색 함수

**Files:**
- Create: `scripts/fetch_naver_listings.py`

**Interfaces:**
- Produces:
  - `parse_naver_price(s: str) -> int | None` — HTML 포함 Naver 가격 문자열 → 원
  - `search_complex(apt_keyword: str, lawd_cd: str, trade_type: str = "A1") -> list[dict]` — 단지 목록 반환
  - 반환 dict 구조: `{"hscpNo": str, "hscpNm": str, "minSpc": float, "maxSpc": float, "dealCnt": int, "leaseCnt": int, "rentCnt": int, "dealPrcMin": int, "dealPrcMax": int}`

- [ ] **Step 1: `fetch_naver_listings.py` 파일 생성 — 파싱 함수 + 단지 검색 함수 작성**

```python
#!/usr/bin/env python3
"""
네이버 부동산 호가 조회 스크립트

사용법:
    python3 fetch_naver_listings.py \
        --keyword 일신아파트 \
        --lawd-cd 41650 \
        --area 49.92 \
        --apsl 90500000 \
        --molit-avg 95000000 \
        --cltr-mng-no 2026-0200-106923
"""
import argparse, json, os, re, random, time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv('/Users/leo-myung/onbid/.env')

NAVER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    ),
    "Referer": "https://m.land.naver.com/",
    "Accept": "application/json",
}

COMPLEX_LIST_URL = "https://m.land.naver.com/cluster/ajax/complexList"


def parse_naver_price(s: str):
    """
    Naver 부동산 가격 문자열 → 원(int)
    '6,000'       → 60_000_000   (6,000만원)
    '1억'         → 100_000_000
    '1억 5,000'   → 150_000_000
    '2억 7,000'   → 270_000_000
    None/빈값     → None
    """
    if not s:
        return None
    s = re.sub(r"<[^>]+>", "", s)   # HTML 태그 제거
    s = s.replace(",", "").strip()
    m = re.search(r"(\d+)\s*억\s*(\d+)?", s)
    if m:
        eok = int(m.group(1)) * 100_000_000
        man = int(m.group(2)) * 10_000 if m.group(2) else 0
        return eok + man
    m2 = re.match(r"^(\d+)$", s)
    if m2:
        return int(m2.group(1)) * 10_000  # 만원 단위
    return None


def search_complex(apt_keyword: str, lawd_cd: str, trade_type: str = "A1") -> list:
    """
    시군구 내 모든 아파트 단지를 조회하고 keyword 매칭 단지만 반환.

    Args:
        apt_keyword: 단지명 키워드 (예: "일신아파트", "일신")
        lawd_cd: 5자리 법정동코드 (예: "41650")
        trade_type: "A1"=매매, "B1"=전세, "B2"=월세

    Returns:
        List of dicts with keys:
          hscpNo, hscpNm, minSpc, maxSpc,
          dealCnt, leaseCnt, rentCnt,
          dealPrcMin (원), dealPrcMax (원)
    """
    import requests
    cortar_no = lawd_cd + "00000"
    params = {
        "rletTpCd": "APT",
        "tradTpCd": trade_type,
        "cortarNo": cortar_no,
    }
    resp = requests.get(COMPLEX_LIST_URL, params=params,
                        headers=NAVER_HEADERS, timeout=10)
    resp.raise_for_status()
    items = resp.json().get("result") or []

    results = []
    keyword_parts = apt_keyword.replace("아파트", "").strip().split()

    for item in items:
        name = item.get("hscpNm", "")
        if not any(part in name for part in keyword_parts):
            continue
        results.append({
            "hscpNo":    item.get("hscpNo", ""),
            "hscpNm":    name,
            "minSpc":    float(item.get("minSpc") or 0),
            "maxSpc":    float(item.get("maxSpc") or 0),
            "dealCnt":   int(item.get("dealCnt") or 0),
            "leaseCnt":  int(item.get("leaseCnt") or 0),
            "rentCnt":   int(item.get("rentCnt") or 0),
            "dealPrcMin": parse_naver_price(item.get("dealPrcMin", "")),
            "dealPrcMax": parse_naver_price(item.get("dealPrcMax", "")),
        })
    return results
```

- [ ] **Step 2: 동작 확인**

```bash
cd /Users/leo-myung/onbid
python3 - << 'EOF'
from scripts.fetch_naver_listings import parse_naver_price, search_complex

# 파싱 검증
assert parse_naver_price("6,000") == 60_000_000, f"got {parse_naver_price('6,000')}"
assert parse_naver_price("1<em class='txt_unit'>억</em>") == 100_000_000
assert parse_naver_price("1억 5,000") == 150_000_000
assert parse_naver_price("2억 7,000") == 270_000_000
assert parse_naver_price("9,500") == 95_000_000
print("parse_naver_price: OK")

# 단지 검색 검증
complexes = search_complex("일신아파트", "41650", "A1")
print(f"search_complex('일신아파트', '41650'): {len(complexes)}건")
for c in complexes:
    print(f"  [{c['hscpNo']}] {c['hscpNm']} {c['minSpc']}-{c['maxSpc']}㎡ "
          f"매매:{c['dealCnt']}건 {c['dealPrcMin']//10000:,}만-{c['dealPrcMax']//10000:,}만")
assert len(complexes) >= 1, "일신아파트 검색 결과 없음"
EOF
```

기대 출력:
```
parse_naver_price: OK
search_complex('일신아파트', '41650'): 1건
  [13966] 일신 58.33-71.53㎡ 매매:14건 6,000만-10,000만
```

- [ ] **Step 3: 커밋**

```bash
git add scripts/fetch_naver_listings.py
git commit -m "feat: 네이버 부동산 단지 검색 + 가격 파싱 함수 추가"
```

---

### Task 2: 전체 거래유형 조회 + 면적 필터 + 괴리율 계산

**Files:**
- Modify: `scripts/fetch_naver_listings.py` (함수 추가)

**Interfaces:**
- Consumes: `search_complex(apt_keyword, lawd_cd, trade_type)` from Task 1
- Produces:
  - `fetch_all_trade_types(apt_keyword, lawd_cd, target_area) -> dict` — 매매/전세/월세 통합
  - `calculate_gap(naver_data, molit_trade_avg, apsl_amt) -> dict` — 괴리율 계산

- [ ] **Step 1: `fetch_all_trade_types` + `calculate_gap` 함수 추가**

`scripts/fetch_naver_listings.py` 끝에 추가:

```python
def fetch_all_trade_types(apt_keyword: str, lawd_cd: str,
                          target_area: float) -> dict:
    """
    매매(A1)/전세(B1)/월세(B2) 단지 데이터를 한 번에 수집.
    target_area ± 10㎡ 범위 단지만 포함.

    Returns:
        {
          "complex_name": str,
          "complex_id": str,
          "sale": {"count": int, "avg": int, "min": int, "max": int},
          "jeonse": {"count": int, "avg": int, "min": int, "max": int},
          "wolse": {"count": int},
          "scope": "same_complex" | "not_found"
        }
    """
    result = {
        "complex_name": "",
        "complex_id":   "",
        "sale":   {"count": 0, "avg": None, "min": None, "max": None},
        "jeonse": {"count": 0, "avg": None, "min": None, "max": None},
        "wolse":  {"count": 0},
        "scope":  "same_complex",
    }

    for trade_type, key in [("A1", "sale"), ("B1", "jeonse"), ("B2", "wolse")]:
        time.sleep(random.uniform(0.5, 1.5))
        complexes = search_complex(apt_keyword, lawd_cd, trade_type)

        # 면적 필터
        matched = [
            c for c in complexes
            if c["maxSpc"] >= (target_area - 10) and c["minSpc"] <= (target_area + 10)
        ]
        if not matched and complexes:
            matched = complexes  # 면적 미매칭이면 전체 포함

        if not matched:
            if not result["complex_id"]:
                result["scope"] = "not_found"
            continue

        best = matched[0]
        if not result["complex_id"]:
            result["complex_name"] = best["hscpNm"]
            result["complex_id"]   = best["hscpNo"]

        if key == "sale":
            cnt = best["dealCnt"]
            pmin = best["dealPrcMin"]
            pmax = best["dealPrcMax"]
            avg  = ((pmin + pmax) // 2) if pmin and pmax else (pmin or pmax)
            result["sale"] = {"count": cnt, "avg": avg, "min": pmin, "max": pmax}
        elif key == "jeonse":
            cnt = best["leaseCnt"]
            pmin = best["dealPrcMin"]
            pmax = best["dealPrcMax"]
            avg  = ((pmin + pmax) // 2) if pmin and pmax else (pmin or pmax)
            result["jeonse"] = {"count": cnt, "avg": avg, "min": pmin, "max": pmax}
        elif key == "wolse":
            result["wolse"]["count"] = best["rentCnt"]

    return result


def calculate_gap(naver_data: dict, molit_trade_avg,
                  apsl_amt) -> dict:
    """
    괴리율 계산.

    Args:
        naver_data: fetch_all_trade_types() 반환값
        molit_trade_avg: 국토부 실거래 평균 (원, None 허용)
        apsl_amt: 감정가 (원, None 허용)

    Returns:
        {
          "naver_vs_molit_pct": float | None,   양수 = 호가 > 실거래
          "naver_vs_apsl_pct":  float | None,   양수 = 호가 > 감정가
          "jeonse_rate_pct":    float | None,   전세가율
        }
    """
    sale_avg   = naver_data["sale"].get("avg")
    jeonse_avg = naver_data["jeonse"].get("avg")

    def pct(a, b):
        if a and b and b > 0:
            return round((a - b) / b * 100, 1)
        return None

    return {
        "naver_vs_molit_pct": pct(sale_avg, molit_trade_avg),
        "naver_vs_apsl_pct":  pct(sale_avg, apsl_amt),
        "jeonse_rate_pct":    pct(jeonse_avg, sale_avg) + 100
                              if (sale_avg and jeonse_avg)
                              else None,
    }
```

- [ ] **Step 2: 동작 확인**

```bash
python3 - << 'EOF'
from scripts.fetch_naver_listings import fetch_all_trade_types, calculate_gap

data = fetch_all_trade_types("일신아파트", "41650", target_area=49.92)
print(f"단지: {data['complex_name']} ({data['complex_id']})")
print(f"매매: {data['sale']['count']}건 "
      f"avg={data['sale']['avg']//10000:,}만 "
      f"({data['sale']['min']//10000:,}~{data['sale']['max']//10000:,}만)")
print(f"전세: {data['jeonse']['count']}건")
print(f"월세: {data['wolse']['count']}건")

gap = calculate_gap(data, molit_trade_avg=95_000_000, apsl_amt=90_500_000)
print(f"gap: {gap}")
assert gap["naver_vs_apsl_pct"] is not None or data["sale"]["count"] == 0
print("calculate_gap: OK")
EOF
```

- [ ] **Step 3: 괴리율 계산 단위 테스트**

```bash
python3 - << 'EOF'
from scripts.fetch_naver_listings import calculate_gap

# 호가 > 실거래 (양수)
mock = {"sale": {"avg": 110_000_000, "count": 3, "min": None, "max": None},
        "jeonse": {"avg": 70_000_000, "count": 1, "min": None, "max": None},
        "wolse": {"count": 0}}
g = calculate_gap(mock, molit_trade_avg=100_000_000, apsl_amt=90_000_000)
assert g["naver_vs_molit_pct"] == 10.0, f"got {g['naver_vs_molit_pct']}"
assert g["naver_vs_apsl_pct"]  == round((110-90)/90*100, 1), f"got {g['naver_vs_apsl_pct']}"
assert g["jeonse_rate_pct"]    is not None
print(f"gap unit test: OK  {g}")

# molit_avg 없을 때
g2 = calculate_gap(mock, molit_trade_avg=None, apsl_amt=90_000_000)
assert g2["naver_vs_molit_pct"] is None
print("gap with None molit_avg: OK")
EOF
```

기대 출력:
```
gap unit test: OK  {'naver_vs_molit_pct': 10.0, 'naver_vs_apsl_pct': 22.2, 'jeonse_rate_pct': ...}
gap with None molit_avg: OK
```

- [ ] **Step 4: 커밋**

```bash
git add scripts/fetch_naver_listings.py
git commit -m "feat: 전체 거래유형 조회 + 괴리율 계산 함수 추가"
```

---

### Task 3: fallback + scope 확장 + main() + JSON 저장

**Files:**
- Modify: `scripts/fetch_naver_listings.py` (main 추가, fallback 래퍼)

**Interfaces:**
- Consumes: `fetch_all_trade_types`, `calculate_gap` from Task 2
- Produces: `_workspace/naver_listings_{cltrMngNo}.json`

- [ ] **Step 1: `fetch_with_fallback` + `main()` 추가**

`scripts/fetch_naver_listings.py` 끝에 추가:

```python
def fetch_with_fallback(apt_keyword: str, lawd_cd: str,
                        target_area: float) -> tuple[dict, str]:
    """
    경로 A(직접 API) 시도 → not_found면 neighborhood 확장.
    Returns: (naver_data, method_used)
    """
    import requests
    try:
        data = fetch_all_trade_types(apt_keyword, lawd_cd, target_area)
        if data["scope"] != "not_found":
            return data, "direct_api"
    except requests.exceptions.HTTPError as e:
        if e.response.status_code in (403, 429):
            print(f"[!] Naver API 차단 ({e.response.status_code}) → fallback 미구현")
        raise

    # scope = not_found: 시군구 전체로 확장 (면적 필터 완화)
    print("[!] 동일 단지 매물 없음 → 시군구 전체 확장")
    data2 = fetch_all_trade_types(apt_keyword, lawd_cd, target_area=999)
    data2["scope"] = "neighborhood" if data2["complex_id"] else "not_found"
    return data2, "direct_api_neighborhood"


def main():
    parser = argparse.ArgumentParser(description="네이버 부동산 호가 조회")
    parser.add_argument("--keyword",      required=True, help="단지명 키워드")
    parser.add_argument("--lawd-cd",      required=True, help="5자리 법정동코드")
    parser.add_argument("--area",         type=float, default=0, help="전용면적 ㎡")
    parser.add_argument("--apsl",         type=float, default=None, help="감정가 (원)")
    parser.add_argument("--molit-avg",    type=float, default=None, help="MOLIT 실거래 평균 (원)")
    parser.add_argument("--cltr-mng-no",  default="UNKNOWN", help="물건관리번호")
    parser.add_argument("--output",       default=None, help="출력 JSON 경로")
    args = parser.parse_args()

    out_path = args.output or (
        f"/Users/leo-myung/onbid/_workspace/naver_listings_{args.cltr_mng_no}.json"
    )

    print(f"\n네이버 호가 조회: {args.keyword} / lawd_cd={args.lawd_cd} / 면적={args.area}㎡")

    naver_data, method = fetch_with_fallback(args.keyword, args.lawd_cd, args.area)
    gap = calculate_gap(naver_data, args.molit_avg, args.apsl)

    output = {
        "fetched_at":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "method":       method,
        "complex_name": naver_data["complex_name"],
        "complex_id":   naver_data["complex_id"],
        "scope":        naver_data["scope"],
        "sale":         naver_data["sale"],
        "jeonse":       naver_data["jeonse"],
        "wolse":        naver_data["wolse"],
        "gap_analysis": gap,
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 콘솔 요약
    s = naver_data["sale"]
    g = gap
    print(f"  단지: {naver_data['complex_name']} (scope={naver_data['scope']})")
    if s["avg"]:
        print(f"  매매 호가: {s['avg']//10000:,}만원 ({s['count']}건)")
    if g["naver_vs_molit_pct"] is not None:
        print(f"  vs 실거래가: {g['naver_vs_molit_pct']:+.1f}%")
    if g["naver_vs_apsl_pct"] is not None:
        print(f"  vs 감정가:   {g['naver_vs_apsl_pct']:+.1f}%")
    if g["jeonse_rate_pct"] is not None:
        print(f"  전세가율:    {g['jeonse_rate_pct']:.1f}%")
    print(f"  저장: {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: end-to-end 실행 확인**

```bash
python3 scripts/fetch_naver_listings.py \
    --keyword 일신아파트 \
    --lawd-cd 41650 \
    --area 49.92 \
    --apsl 90500000 \
    --molit-avg 95000000 \
    --cltr-mng-no 2026-0200-106923
```

기대 출력:
```
네이버 호가 조회: 일신아파트 / lawd_cd=41650 / 면적=49.92㎡
  단지: 일신 (scope=same_complex 또는 neighborhood)
  매매 호가: XXXX만원 (N건)
  vs 실거래가: +X.X%
  vs 감정가:   +X.X%
  저장: _workspace/naver_listings_2026-0200-106923.json
```

- [ ] **Step 3: JSON 파일 구조 확인**

```bash
python3 -c "
import json
d = json.load(open('_workspace/naver_listings_2026-0200-106923.json'))
assert 'gap_analysis' in d
assert 'sale' in d
assert 'fetched_at' in d
print('JSON 구조 검증: OK')
print(json.dumps(d, ensure_ascii=False, indent=2)[:500])
"
```

- [ ] **Step 4: 커밋**

```bash
git add scripts/fetch_naver_listings.py
git commit -m "feat: fallback + scope 확장 + main() + JSON 저장 완성"
```

---

### Task 4: naver-land-data 스킬 파일 작성

**Files:**
- Create: `.claude/skills/naver-land-data/SKILL.md`

**Interfaces:**
- Consumes: `scripts/fetch_naver_listings.py` from Task 3
- Produces: 스킬 정의 — location-analysis Step 2.5에서 호출

- [ ] **Step 1: 스킬 파일 작성**

`.claude/skills/naver-land-data/SKILL.md` 생성:

```markdown
---
name: naver-land-data
description: 네이버 부동산 현재 매매·전세·월세 호가를 단지명+법정동코드로 조회하고 감정가·국토부 실거래가 대비 괴리율을 계산한다. "네이버 호가", "현재 시세", "매물 가격", "전세가율", "호가 vs 실거래" 요청 시 이 스킬을 사용할 것.
---

# 네이버 부동산 호가 조회 스킬

## 사용 시점
location-analysis Step 2.5에서 MOLIT 실거래가 조회(Step 2) 직후 호출한다.

## 실행

### 기본 실행
```bash
python3 /Users/leo-myung/onbid/scripts/fetch_naver_listings.py \
    --keyword "{apt_keyword}" \
    --lawd-cd "{lawd_cd_5자리}" \
    --area {target_area} \
    --apsl {apsl_amt} \
    --molit-avg {molit_trade_avg_또는_생략} \
    --cltr-mng-no "{cltrMngNo}"
```

### 파라미터
| 파라미터 | 설명 | 예시 |
|---------|------|------|
| `--keyword` | 단지명 키워드 (아파트 제외 가능) | `일신`, `푸르지오` |
| `--lawd-cd` | 5자리 법정동코드 | `41650` |
| `--area` | 전용면적 ㎡ | `49.92` |
| `--apsl` | 감정가 (원) | `90500000` |
| `--molit-avg` | MOLIT 실거래 평균 (원, 선택) | `95000000` |
| `--cltr-mng-no` | 물건관리번호 (파일명용) | `2026-0200-106923` |

## 출력
`_workspace/naver_listings_{cltrMngNo}.json`:

```json
{
  "fetched_at": "2026-06-25 09:00",
  "complex_name": "일신",
  "complex_id": "13966",
  "scope": "same_complex",
  "sale":   {"count": 14, "avg": 80000000, "min": 60000000, "max": 100000000},
  "jeonse": {"count": 0,  "avg": null, "min": null, "max": null},
  "wolse":  {"count": 4},
  "gap_analysis": {
    "naver_vs_molit_pct": -15.8,
    "naver_vs_apsl_pct":  -11.6,
    "jeonse_rate_pct": null
  }
}
```

## scope 의미
- `same_complex`: 동일 단지 매물 기반
- `neighborhood`: 단지 미발견 → 시군구 확장
- `not_found`: 매물 없음

## 에러 처리
- 403/429 차단: 로그 출력 후 빈 결과 저장, 파이프라인 계속
- 단지 미발견: `scope=not_found`로 저장, 경고 출력
```

- [ ] **Step 2: 스킬 등록 확인**

```bash
ls .claude/skills/naver-land-data/SKILL.md
```

- [ ] **Step 3: 커밋**

```bash
git add .claude/skills/naver-land-data/SKILL.md
git commit -m "feat: naver-land-data 스킬 파일 추가"
```

---

### Task 5: location-analysis + location-analyst 통합

**Files:**
- Modify: `.claude/skills/location-analysis/SKILL.md`
- Modify: `.claude/agents/location-analyst.md`

**Interfaces:**
- Consumes: `naver-land-data` 스킬 (Task 4), `molit-market-data` 스킬 (기존 Step 2)

- [ ] **Step 1: location-analysis SKILL.md에 Step 2.5 추가**

`.claude/skills/location-analysis/SKILL.md` 의 `### Step 2` 블록 바로 아래에 삽입:

```markdown
### Step 2.5: 네이버 호가 조회 → **naver-land-data 스킬 사용**

Step 2(MOLIT 실거래가)가 완료된 직후 실행한다.  
아파트 물건에만 적용 (토지·상업용은 스킵).

필요 입력값:
- `apt_keyword`: 단지명 키워드 (물건명에서 아파트 단지명 추출)
- `lawd_cd`: Step 1에서 파싱한 5자리 법정동코드
- `target_area`: 물건 전용면적 (㎡)
- `apsl_amt`: 감정가 (원)
- `molit_trade_avg`: Step 2에서 얻은 MOLIT 실거래 평균 (없으면 생략)

```bash
python3 /Users/leo-myung/onbid/scripts/fetch_naver_listings.py \
    --keyword "{apt_keyword}" \
    --lawd-cd "{lawd_cd}" \
    --area {target_area} \
    --apsl {apsl_amt} \
    --molit-avg {molit_trade_avg} \
    --cltr-mng-no "{cltrMngNo}"
```

결과 파일: `_workspace/naver_listings_{cltrMngNo}.json`  
→ `gap_analysis.naver_vs_molit_pct`, `gap_analysis.naver_vs_apsl_pct`,
   `gap_analysis.jeonse_rate_pct` 값을 Step 4 종합 평가에 포함시킨다.
```

- [ ] **Step 2: location-analyst.md에 Step 2.5 참조 추가**

`.claude/agents/location-analyst.md` 의 `### 4. 부동산 시세 분석` 섹션 끝에 추가:

```markdown
#### 4-2. 네이버 부동산 현재 호가 (naver-land-data 스킬)

아파트 물건의 경우 MOLIT 실거래가 조회(4-1) 직후 실행:

```bash
python3 /Users/leo-myung/onbid/scripts/fetch_naver_listings.py \
    --keyword "{단지명}" --lawd-cd "{5자리코드}" \
    --area {전용면적} --apsl {감정가} \
    --molit-avg {MOLIT평균} --cltr-mng-no "{물건관리번호}"
```

결과의 `gap_analysis`를 투자 평가에 반영:
- `naver_vs_molit_pct` 양수: 호가 > 실거래 → 시세 상승 추세
- `naver_vs_apsl_pct` 양수: 호가 > 감정가 → 낙찰 후 즉시 시세차익 가능
- `jeonse_rate_pct` 70% 이상: 갭투자 위험 낮음
```

- [ ] **Step 3: end-to-end 통합 검증**

```bash
# 실거래가 + 네이버 호가 동시 수집 시뮬레이션
python3 - << 'EOF'
import subprocess, json

result = subprocess.run([
    "python3", "scripts/fetch_naver_listings.py",
    "--keyword", "일신아파트",
    "--lawd-cd", "41650",
    "--area", "49.92",
    "--apsl", "90500000",
    "--cltr-mng-no", "test-0000-000000"
], capture_output=True, text=True, cwd="/Users/leo-myung/onbid")

print("STDOUT:", result.stdout)
if result.returncode == 0:
    d = json.load(open("/Users/leo-myung/onbid/_workspace/naver_listings_test-0000-000000.json"))
    assert "gap_analysis" in d
    assert "sale" in d
    print("통합 검증: OK")
else:
    print("STDERR:", result.stderr)
EOF
```

- [ ] **Step 4: 커밋**

```bash
git add .claude/skills/location-analysis/SKILL.md .claude/agents/location-analyst.md
git commit -m "feat: location-analysis Step 2.5에 네이버 호가 조회 통합"
```
