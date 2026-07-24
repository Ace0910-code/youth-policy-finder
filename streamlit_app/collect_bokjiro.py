# -*- coding: utf-8 -*-
"""
복지로 중앙부처복지서비스 수집기 (확장, XML)

  GET https://apis.data.go.kr/B554287/NationalWelfareInformationsV001/NationalWelfarelistV001
  ⚠️ 필수 params: serviceKey, callTp=L, srchKeyCode=003, pageNo, numOfRows
     (callTp / srchKeyCode 빠지면 INVALID_REQUEST_PARAMETER_ERROR)
  XML 응답: 루트 wantedList, 항목 servList
  청년 필터: lifeArray에 "청년" 포함 항목만 (전체 461건 중 약 165건)
  ⚠️ 일일 호출 100건 제한 → numOfRows 크게, 페이지 수 최소화

사용:
  python collect_bokjiro.py --demo
  set ODCLOUD_API_KEY=... && python collect_bokjiro.py
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

API_URL = ("https://apis.data.go.kr/B554287/NationalWelfareInformationsV001/"
           "NationalWelfarelistV001")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(BASE_DIR, "data", "bokjiro.json")

THEME_CATEGORY = {
    "주거": "주거", "일자리": "취업·창업", "고용": "취업·창업",
    "교육": "교육·역량", "장학": "교육·장학",
}


def map_category(themes):
    for key, cat in THEME_CATEGORY.items():
        if key in str(themes or ""):
            return cat
    return "생활·교통"


def parse_items(xml_text):
    """wantedList XML → dict 리스트 (servList 항목들)"""
    root = ET.fromstring(xml_text)
    items = []
    for node in root.iter("servList"):
        items.append({child.tag: (child.text or "").strip() for child in node})
    return items


def total_count(xml_text):
    root = ET.fromstring(xml_text)
    tc = root.findtext(".//totalCount")
    return int(tc) if tc and tc.isdigit() else 0


def is_youth(item):
    return "청년" in item.get("lifeArray", "")


SPECIAL_KEYS = ("자립준비", "보호종료", "한부모", "다문화", "북한이탈", "탈북",
                "장애인", "국가유공", "기초생활수급", "차상위", "농업인", "예술인",
                "제대군인", "출소", "보호관찰")


def to_schema(item):
    summary = item.get("servDgst", "").replace("\n", " ")
    text = item.get("servNm", "") + " " + summary
    special_req = summary[:80] if any(k in text for k in SPECIAL_KEYS) else ""
    if len(summary) > 120:
        summary = summary[:117] + "..."
    link = item.get("servDtlLink", "")
    if link and not link.startswith("http"):
        link = "https://www.bokjiro.go.kr" + link
    return {
        "id": f"BK-{item.get('servId', '')}",
        "name": item.get("servNm", ""),
        "category": map_category(item.get("intrsThemaArray")),
        "org": item.get("jurMnofNm", ""),
        "summary": summary,
        "amount_max": None,               # 목록 API에는 금액 정보 없음
        "amount_label": item.get("srvPvsnNm", ""),
        "apply_start": "",
        "apply_end": "상시",
        "url": link,
        "special_req": special_req,
        "status_label": "신청 가능",
        "benefit_score": 0.35,
        "keywords": [t for t in str(item.get("intrsThemaArray", "")).split(",") if t][:6],
        "eligibility": {
            "age_min": 19, "age_max": 39,   # lifeArray '청년' 기준 보수적 범위
            "regions": ["전국"],             # 중앙부처복지서비스 → 전국
            "income_max_pct": None,
            "status": [],
            "housing": [],
        },
    }


def fetch_all(service_key, num_of_rows=500):
    """일일 100건 호출 제한이 있으므로 한 번에 최대한 크게 요청한다."""
    import requests
    items, page = [], 1
    while True:
        r = requests.get(API_URL, params={
            "serviceKey": service_key,
            "callTp": "L",                 # ⚠️ 필수
            "srchKeyCode": "003",          # ⚠️ 필수
            "pageNo": page,
            "numOfRows": num_of_rows,
        }, timeout=30)
        r.raise_for_status()
        if "INVALID_REQUEST_PARAMETER_ERROR" in r.text:
            raise RuntimeError("필수 파라미터 누락(callTp/srchKeyCode 확인): " + r.text[:200])
        batch = parse_items(r.text)
        items.extend(batch)
        total = total_count(r.text)
        print(f"  page {page}: {len(batch)}건 (누적 {len(items)}/{total})")
        if not batch or len(items) >= total:
            break
        page += 1
    return items


# ── 데모용 원본 XML 샘플 ────────────────────────────────────
DEMO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<wantedList>
  <totalCount>3</totalCount>
  <servList>
    <servId>WLF00000001</servId>
    <servNm>청년내일저축계좌</servNm>
    <servDgst>일하는 저소득 청년의 자산형성을 지원하여 자립 기반 마련을 돕습니다.</servDgst>
    <servDtlLink>/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?wlfareInfoId=WLF00000001</servDtlLink>
    <jurMnofNm>보건복지부</jurMnofNm>
    <lifeArray>청년</lifeArray>
    <intrsThemaArray>일자리,서민금융</intrsThemaArray>
    <srvPvsnNm>현금지급</srvPvsnNm>
  </servList>
  <servList>
    <servId>WLF00000002</servId>
    <servNm>노인 무릎인공관절 수술 지원</servNm>
    <servDgst>저소득층 노인에게 무릎인공관절 수술비를 지원합니다.</servDgst>
    <servDtlLink>/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?wlfareInfoId=WLF00000002</servDtlLink>
    <jurMnofNm>보건복지부</jurMnofNm>
    <lifeArray>노년</lifeArray>
    <intrsThemaArray>신체건강</intrsThemaArray>
    <srvPvsnNm>현금지급</srvPvsnNm>
  </servList>
  <servList>
    <servId>WLF00000003</servId>
    <servNm>청년 주거급여 분리지급</servNm>
    <servDgst>부모와 떨어져 거주하는 청년에게 주거급여를 분리하여 지급합니다.</servDgst>
    <servDtlLink>/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?wlfareInfoId=WLF00000003</servDtlLink>
    <jurMnofNm>국토교통부</jurMnofNm>
    <lifeArray>청년,중장년</lifeArray>
    <intrsThemaArray>주거,생활지원</intrsThemaArray>
    <srvPvsnNm>현금지급</srvPvsnNm>
  </servList>
</wantedList>"""


def run_demo():
    print("[demo] 복지로 XML 파싱·매핑 검증 (키 불필요)")
    items = parse_items(DEMO_XML)
    youth = [x for x in items if is_youth(x)]
    mapped = [to_schema(x) for x in youth]
    checks = [
        ("XML servList 파싱", len(items) == 3, f"{len(items)}건"),
        ("totalCount 파싱", total_count(DEMO_XML) == 3, str(total_count(DEMO_XML))),
        ("lifeArray 청년 필터", len(youth) == 2 and all("청년" in y["lifeArray"] for y in youth),
         f"{len(items)}건 중 {len(youth)}건"),
        ("노년 정책 제외", all("노인" not in m["name"] for m in mapped),
         ", ".join(m["name"] for m in mapped)),
        ("주거 테마 → 주거 분류", mapped[1]["category"] == "주거", mapped[1]["category"]),
        ("상세링크 절대경로화", mapped[0]["url"].startswith("https://www.bokjiro.go.kr/"),
         mapped[0]["url"][:60] + "..."),
    ]
    ok = True
    for name, passed, detail in checks:
        print(f"  {'✅' if passed else '❌'} {name}: {detail}")
        ok &= passed
    print(f"[demo] {'모든 검증 통과' if ok else '검증 실패 항목 있음'} "
          f"({sum(1 for _, p, _ in checks if p)}/{len(checks)})")
    return 0 if ok else 1


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="복지로 중앙부처복지서비스 수집기")
    ap.add_argument("--demo", action="store_true", help="키 없이 파싱·매핑 검증")
    args = ap.parse_args()

    if args.demo:
        sys.exit(run_demo())

    import keys as keyloader
    key = keyloader.get_key("ODCLOUD_API_KEY")
    if not key:
        print("환경변수 ODCLOUD_API_KEY가 없습니다. (data.go.kr 개인 인증키, 복지로 API 활용신청 필요)\n"
              "  키 없이 검증만 하려면: python collect_bokjiro.py --demo")
        sys.exit(1)

    print("복지로 복지서비스 수집... (일일 100회 호출 제한 주의)")
    raw = fetch_all(key)
    youth = [x for x in raw if is_youth(x)]
    policies = [p for p in (to_schema(x) for x in youth) if p["name"]]
    if not policies:
        print("⚠️ 수집 결과가 0건입니다 (일일 100회 한도 소진 가능성). "
              "기존 파일을 보존하고 종료합니다.")
        sys.exit(1)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(policies, f, ensure_ascii=False, indent=2)
    print(f"완료: 전체 {len(raw)}건 중 청년 {len(policies)}건 → {OUT_PATH}")


if __name__ == "__main__":
    main()
