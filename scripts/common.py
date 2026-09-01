#!/usr/bin/env python3
"""
scripts/ 공통 유틸리티

- 저장소 루트/워크스페이스 경로 (실행 위치·PC에 무관)
- .env 로드 및 API 키 조회 (Encoding/Decoding 키 모두 허용, unquote 처리)
- 공공데이터포털 온비드 API 호출 + 응답 파싱 (header/body 또는 result 형식 모두 처리)
- 금액 포맷터

모든 스크립트는 이 모듈을 통해 경로·키를 얻는다. 절대경로를 하드코딩하지 말 것.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / '_workspace'
ONBID_BASE = "https://apis.data.go.kr/B010003"
MOLIT_BASE = "https://apis.data.go.kr/1613000"

_ENV_LOADED = False


def load_env() -> None:
    """저장소 루트의 .env를 1회만 로드한다."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env')
    except ImportError:
        # python-dotenv 미설치 시 최소 파서로 대체
        env_path = ROOT / '.env'
        if env_path.exists():
            for line in env_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())
    _ENV_LOADED = True


def get_key(name: str, required: bool = True) -> str:
    """환경변수에서 API 키를 읽어 URL-decode 하여 반환."""
    load_env()
    key = unquote(os.getenv(name, '') or '')
    if required and not key:
        raise SystemExit(f"[!] {name} 가 비어 있습니다. {ROOT / '.env'} 를 확인하세요 "
                         f"(.env.example 참고).")
    return key


def parse_onbid_response(data: dict):
    """
    온비드 JSON 응답을 (items, error) 로 정규화한다.
    - 정상: header.resultCode == '00' → (list, None)
    - NODATA(03) 또는 DB_ERROR: ([], None)  ← 정상 skip 케이스
    - 그 외 오류: (None, '메시지')
    """
    header = data.get('header') or data.get('result') or {}
    rc = str(header.get('resultCode', '00') or '00')
    msg = header.get('resultMsg', '') or ''
    if rc == '03' or 'DB_ERROR' in msg:
        return [], None
    if rc not in ('00', ''):
        return None, f"API 오류 {rc}: {msg}"
    items_raw = (data.get('body') or {}).get('items', {})
    items = items_raw.get('item', []) if isinstance(items_raw, dict) else (items_raw or [])
    if not isinstance(items, list):
        items = [items] if items else []
    return items, None


def onbid_get(svc: str, op: str, params: dict, rows: int = 10, page: int = 1,
              timeout: int = 20, retries: int = 3, key: str | None = None):
    """
    온비드 API GET 호출. 429/타임아웃/빈 응답은 재시도.
    반환: (items, error)  — parse_onbid_response 규약과 동일
    """
    import requests
    key = key or get_key('ONBID_API_KEY')
    url = f"{ONBID_BASE}/{svc}/{op}"
    p = {'serviceKey': key, 'pageNo': page, 'numOfRows': rows, 'resultType': 'json', **params}
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=p, timeout=timeout)
            if r.status_code == 429:
                wait = int(r.headers.get('Retry-After', 30))
                print(f"    [!] Rate limit(429) — {wait}초 대기 후 재시도")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}: {r.text[:200]}"
            if not r.text.strip():
                raise ValueError("빈 응답")
            return parse_onbid_response(r.json())
        except (requests.exceptions.Timeout, ValueError) as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
        except requests.exceptions.RequestException as e:
            return None, f"네트워크 오류: {e}"
    return None, f"재시도 실패: {last_err}"


def format_price(v) -> str:
    """원 단위 금액 → '3.2억' / '4,240만' 표기."""
    if v is None or v == '':
        return '-'
    try:
        v = float(v)
    except (TypeError, ValueError):
        return '-'
    if v == 0:
        return '0'
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}억".replace('.00억', '억')
    return f"{int(round(v / 1e4)):,}만"


def to_float(v, default=0.0) -> float:
    try:
        return float(v) if v not in (None, '') else default
    except (TypeError, ValueError):
        return default


def to_int(v, default=0) -> int:
    try:
        return int(float(v)) if v not in (None, '') else default
    except (TypeError, ValueError):
        return default


def now_stamp(fmt: str = '%Y-%m-%d %H:%M') -> str:
    return datetime.now().strftime(fmt)
