"""snapshot_market.py / build_meteor.py — 주소 분해, 압축, 템플릿 삽입 (네트워크 없음)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

from snapshot_market import split_addr  # noqa: E402
from build_meteor import build, compact  # noqa: E402


def test_split_addr_short_sido_and_masked_sgg():
    assert split_addr('강원특별자치도 정선군 ****') == ('강원', '정선군')
    assert split_addr('서울특별시 은평구 대조동 93-3') == ('서울', '은평구')
    assert split_addr('경기도 ******') == ('경기', '')
    assert split_addr('') == ('기타', '')


SNAP = {
    'snapshot_at': '2026-09-02 08:00', 'pbanc_count': 2,
    'properties': [
        {'id': 'A', 'pbanc': 'P1', 'name': 'a', 'addr': '', 'sido': '서울', 'sgg': '', 'usageL': '부동산', 'usageM': '주거용건물',
         'usageS': '아파트', 'apsl': 1e8, 'usbdNft': 1,
         'rounds': [{'nsq': '001', 'cdtn': 1, 'bgn': '202609011000', 'end': '202609031700', 'price': 1e8, 'stat': '0001'},
                    {'nsq': '002', 'cdtn': 2, 'bgn': '202609081000', 'end': '202609101700', 'price': None, 'stat': '0001'}]},
        {'id': 'B', 'pbanc': 'P2', 'name': 'bike', 'addr': '', 'sido': '전남', 'sgg': '', 'usageL': '동산', 'usageM': '차량',
         'usageS': '오토바이', 'apsl': 1e5, 'usbdNft': 0, 'rounds': [{'nsq': '1', 'cdtn': 3, 'bgn': '202609011000', 'end': '202609031700', 'price': 1e5, 'stat': '0001'}]},
        {'id': 'C', 'pbanc': 'P2', 'name': 'noapsl', 'addr': '', 'sido': '경기', 'sgg': '', 'usageL': '부동산', 'usageM': '토지',
         'usageS': '대지', 'apsl': None, 'usbdNft': 0, 'rounds': []},
    ],
}


def test_compact_filters_non_realestate_and_priceless_rounds():
    c = compact(SNAP)
    assert [p[0] for p in c['properties']] == ['A']            # 동산·감정가 없음 제외
    a = c['properties'][0]
    assert a[:8] == ['A', 'a', '서울', '', '주거용건물', '아파트', 100000000, 1]
    assert a[8] == ['001', 202609011000, 202609031700, 100000000]   # price None 회차 제외, 4개 단위 평탄화


def test_build_embeds_json_and_escapes_script(tmp_path):
    snap = json.loads(json.dumps(SNAP))
    snap['properties'][0]['name'] = 'x</script><b>'
    inp = tmp_path / 's.json'
    inp.write_text(json.dumps(snap), encoding='utf-8')
    out = build(inp, tmp_path / 'm.html')
    html = out.read_text(encoding='utf-8')
    assert '__METEOR_DATA__' not in html
    assert '<\\/script>' in html and 'x</script>' not in html.split('id="data">')[1].split('</script>')[0]
    assert '<title>공매 유성우</title>' in html
