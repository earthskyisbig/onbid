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
