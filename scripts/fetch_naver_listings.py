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
            result["jeonse"] = {"count": cnt, "avg": None, "min": None, "max": None}
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
        "jeonse_rate_pct":    round(jeonse_avg / sale_avg * 100, 1)
                              if (sale_avg and jeonse_avg)
                              else None,
    }


def fetch_with_fallback(apt_keyword: str, lawd_cd: str,
                        target_area: float) -> tuple:
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

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
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
