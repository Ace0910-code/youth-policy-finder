# -*- coding: utf-8 -*-
"""
정부24 공공서비스(혜택) 수집기 (★준핵심, odcloud)

  목록:      GET https://api.odcloud.kr/api/gov24/v3/serviceList
  정밀자격:  GET https://api.odcloud.kr/api/gov24/v3/supportConditions
  params: page, perPage, returnType=JSON, serviceKey, cond[서비스명::LIKE]=청년

supportConditions 조인(서비스ID 기준):
  JA0110 = 최소연령(정수), JA0111 = 최대연령(정수)
  JA0201~JA0205 = 소득구간 flag(저→고, "Y") — 가장 높은 Y 구간의 상한을 근사치로:
    JA0205→무관(None), JA0204→200, JA0203→100, JA0202→75, JA0201→50

사용:
  python collect_gov24.py --demo
  set ODCLOUD_API_KEY=... && python collect_gov24.py
"""
import argparse
import json
import os
import re
import sys

LIST_URL = "https://api.odcloud.kr/api/gov24/v3/serviceList"
COND_URL = "https://api.odcloud.kr/api/gov24/v3/supportConditions"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(BASE_DIR, "data", "gov24.json")

FIELD_MAP = {  # 서비스분야 → 공통 카테고리
    "주거": "주거", "자립": "주거",
    "고용": "취업·창업", "창업": "취업·창업", "일자리": "취업·창업",
    "보육": "교육·장학", "교육": "교육·장학",
}

SIDO_NAMES = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
              "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]

# 전체 명칭 → 시도 리스트 (긴 이름 먼저 검사해야 '충청남도'가 '전국'으로 새지 않음)
SIDO_FULL = [
    ("전남광주통합특별시", ["전남", "광주"]),      # 행정통합 명칭
    ("서울특별시", ["서울"]), ("부산광역시", ["부산"]), ("대구광역시", ["대구"]),
    ("인천광역시", ["인천"]), ("광주광역시", ["광주"]), ("대전광역시", ["대전"]),
    ("울산광역시", ["울산"]), ("세종특별자치시", ["세종"]), ("경기도", ["경기"]),
    ("강원특별자치도", ["강원"]), ("강원도", ["강원"]), ("충청북도", ["충북"]),
    ("충청남도", ["충남"]), ("전북특별자치도", ["전북"]), ("전라북도", ["전북"]),
    ("전라남도", ["전남"]), ("경상북도", ["경북"]), ("경상남도", ["경남"]),
    ("제주특별자치도", ["제주"]), ("제주도", ["제주"]),
]

# (플래그, 중위소득% 상한) — 높은 구간부터 검사
INCOME_FLAGS = [("JA0205", None), ("JA0204", 200), ("JA0203", 100),
                ("JA0202", 75), ("JA0201", 50)]


def map_category(field):
    for key, cat in FIELD_MAP.items():
        if key in str(field or ""):
            return cat
    return "생활·교통"


def map_income(cond):
    """가장 높은 'Y' 구간의 상한을 income_max_pct 근사로. 플래그 전무 → 무관."""
    if not cond:
        return None
    flagged = [(f, pct) for f, pct in INCOME_FLAGS if str(cond.get(f, "")).upper() == "Y"]
    if not flagged:
        return None
    return flagged[0][1]      # INCOME_FLAGS가 높은 구간부터이므로 첫 항목이 최고 Y 구간


def map_age(cond):
    def to_int(v):
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return None
    if not cond:
        return 0, 200
    a_min = to_int(cond.get("JA0110"))
    a_max = to_int(cond.get("JA0111"))
    return (a_min if a_min is not None else 0,
            a_max if a_max not in (None, 0) else 200)


def map_region(org_name, target_text):
    """정부24는 지역 필드가 없어 소관기관명에서 시도를 찾되,
    중앙부처(부·처·청·위원회)는 전국으로 처리한다."""
    org = str(org_name or "").strip()
    if re.search(r"(부|처|청|위원회)$", org):
        return ["전국"]
    for full, sidos in SIDO_FULL:      # '충청남도 보령시' → 충남
        if full in org:
            return list(sidos)
    for sido in SIDO_NAMES:            # 축약 표기 대비
        if sido in org:
            return [sido]
    return ["전국"]


def parse_deadline(text):
    """'신청기한' 텍스트 → (start, end). 날짜 못 찾으면 상시 취급."""
    dates = re.findall(r"(\d{4})[.\-/년\s]*(\d{1,2})[.\-/월\s]*(\d{1,2})", str(text or ""))
    fmt = lambda d: f"{d[0]}.{int(d[1]):02d}.{int(d[2]):02d}"
    if len(dates) >= 2:
        return fmt(dates[0]), fmt(dates[1])
    if len(dates) == 1:
        return "", fmt(dates[0])
    return "", "상시"


def clean_url(u):
    """URL 정제: 이중 스킴·공백·비URL 텍스트 방어, 스킴 보정"""
    u = str(u or "").strip()
    u = re.sub(r"^(https?://)+(?=https?://)", "", u)
    if " " in u:
        u = u.split()[0]
    if not u or re.search(r"[가-힣]", u) or "." not in u:
        return ""
    if not u.startswith("http"):
        u = "https://" + u
    return u


def parse_amount(text):
    amounts = []
    for m in re.finditer(r"([\d,.]+)\s*억", str(text or "")):
        try:
            amounts.append(int(float(m.group(1).replace(",", "")) * 100_000_000))
        except ValueError:
            pass
    for m in re.finditer(r"([\d,]+)\s*만\s*원", str(text or "")):
        try:
            amounts.append(int(m.group(1).replace(",", "")) * 10_000)
        except ValueError:
            pass
    if not amounts:
        return None, ""
    best = max(amounts)
    if best >= 1_000_000_000:      # 사업 총예산 오파싱 방지
        return None, ""
    label = (f"최대 {best / 100_000_000:.1f}억원".replace(".0억", "억")
             if best >= 100_000_000 else f"최대 {best // 10_000:,}만원")
    return best, label


def to_schema(svc, cond=None):
    """serviceList 1건 + supportConditions 1건(조인) → 공통 스키마"""
    a_min, a_max = map_age(cond)
    start, end = parse_deadline(svc.get("신청기한"))
    if start and end not in ("", "상시") and end < start:   # 원본 연도 오타 → 확인 필요 처리
        end = "상시"
    support = svc.get("지원내용", "") or ""
    amount, label = parse_amount(support)
    summary = (svc.get("서비스목적요약") or support).strip().replace("\n", " ")
    if len(summary) > 120:
        summary = summary[:117] + "..."
    target = svc.get("지원대상", "") or ""

    return {
        "id": f"GV-{svc.get('서비스ID', '')}",
        "name": (svc.get("서비스명") or "").strip(),
        "category": map_category(svc.get("서비스분야")),
        "org": (svc.get("소관기관명") or "").strip(),
        "summary": summary,
        "amount_max": amount,
        "amount_label": label,
        "apply_start": start,
        "apply_end": end,
        "url": clean_url(svc.get("상세조회URL")),
        "status_label": "신청 가능",
        "benefit_score": min(1.0, 0.2 + (amount or 0) / 10_000_000 * 0.8) if amount else 0.3,
        "keywords": [w for w in re.findall(r"[가-힣]{2,}", svc.get("서비스명", ""))][:6],
        "eligibility": {
            "age_min": a_min, "age_max": a_max,
            "regions": map_region(svc.get("소관기관명"), target),
            "income_max_pct": map_income(cond),
            "status": [],
            "housing": ["무주택"] if "무주택" in target else [],
        },
    }


def fetch_paged(url, service_key, per_page=500, max_pages=30, extra=None):
    import requests
    rows, page = [], 1
    while page <= max_pages:
        params = {"page": page, "perPage": per_page,
                  "returnType": "JSON", "serviceKey": service_key,
                  "cond[서비스명::LIKE]": "청년"}
        if extra:
            params.update(extra)
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        body = r.json()
        batch = body.get("data", []) or []
        rows.extend(batch)
        total = int(body.get("matchCount", body.get("totalCount", 0)) or 0)
        print(f"  page {page}: {len(batch)}건 (누적 {len(rows)}/{total})")
        if not batch or len(rows) >= total:
            break
        page += 1
    return rows


# ── 데모용 원본 샘플 ─────────────────────────────────────────
DEMO_SERVICES = [
    {
        "서비스ID": "SVC001", "서비스명": "청년 주거급여 분리지급",
        "서비스분야": "주거·자립", "서비스목적요약": "부모와 떨어져 사는 청년에게 주거급여를 별도 지급",
        "지원대상": "만 19세 이상 30세 미만 무주택 미혼 청년", "선정기준": "중위소득 47% 이하",
        "지원내용": "지역별 기준임대료 상한 내 실비 지급, 월 최대 34만원",
        "신청기한": "상시신청", "상세조회URL": "https://www.gov.kr/svc001",
        "소관기관명": "국토교통부", "지원유형": "현금",
    },
    {
        "서비스ID": "SVC002", "서비스명": "서울시 청년 마음건강 지원",
        "서비스분야": "보건·의료", "서비스목적요약": "청년 심리상담 바우처 제공",
        "지원대상": "서울 거주 청년", "선정기준": "만 19~39세",
        "지원내용": "심리상담 10회, 약 60만원 상당 바우처",
        "신청기한": "2024.07.01.~2024.07.31.", "상세조회URL": "https://www.gov.kr/svc002",
        "소관기관명": "서울특별시", "지원유형": "이용권",
    },
]
DEMO_CONDITIONS = [
    {"서비스ID": "SVC001", "JA0110": 19, "JA0111": 29,
     "JA0201": "Y", "JA0202": "", "JA0203": "", "JA0204": "", "JA0205": ""},
    {"서비스ID": "SVC002", "JA0110": 19, "JA0111": 39,
     "JA0201": "Y", "JA0202": "Y", "JA0203": "Y", "JA0204": "Y", "JA0205": "Y"},
]


def run_demo():
    print("[demo] 정부24 매핑 검증 (키 불필요)")
    cond_by_id = {c["서비스ID"]: c for c in DEMO_CONDITIONS}
    mapped = [to_schema(s, cond_by_id.get(s["서비스ID"])) for s in DEMO_SERVICES]
    checks = [
        ("연령 조인(JA0110/0111)", (mapped[0]["eligibility"]["age_min"],
                                   mapped[0]["eligibility"]["age_max"]) == (19, 29),
         f"{mapped[0]['eligibility']['age_min']}~{mapped[0]['eligibility']['age_max']}"),
        ("소득 JA0201만 Y → 50%", mapped[0]["eligibility"]["income_max_pct"] == 50,
         str(mapped[0]["eligibility"]["income_max_pct"])),
        ("소득 JA0205까지 Y → 무관", mapped[1]["eligibility"]["income_max_pct"] is None,
         str(mapped[1]["eligibility"]["income_max_pct"])),
        ("분야 주거·자립 → 주거", mapped[0]["category"] == "주거", mapped[0]["category"]),
        ("중앙부처 → 전국", mapped[0]["eligibility"]["regions"] == ["전국"],
         str(mapped[0]["eligibility"]["regions"])),
        ("광역지자체 → 서울", mapped[1]["eligibility"]["regions"] == ["서울"],
         str(mapped[1]["eligibility"]["regions"])),
        ("무주택 감지", mapped[0]["eligibility"]["housing"] == ["무주택"],
         str(mapped[0]["eligibility"]["housing"])),
        ("상시 기한", mapped[0]["apply_end"] == "상시", mapped[0]["apply_end"]),
        ("기간 파싱", mapped[1]["apply_end"] == "2024.07.31", mapped[1]["apply_end"]),
        ("금액 파싱(34만원)", mapped[0]["amount_max"] == 340_000,
         f"{mapped[0]['amount_max']:,}"),
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
    ap = argparse.ArgumentParser(description="정부24 공공서비스 수집기")
    ap.add_argument("--demo", action="store_true", help="키 없이 매핑 검증")
    args = ap.parse_args()

    if args.demo:
        sys.exit(run_demo())

    import keys as keyloader
    key = keyloader.get_key("ODCLOUD_API_KEY")
    if not key:
        print("환경변수 ODCLOUD_API_KEY가 없습니다. (data.go.kr 개인 인증키, gov24 API 활용신청 필요)\n"
              "  키 없이 매핑만 확인하려면: python collect_gov24.py --demo")
        sys.exit(1)

    print("정부24 서비스 목록 수집...")
    services = fetch_paged(LIST_URL, key)
    print("정부24 지원조건 수집...")
    conditions = fetch_paged(COND_URL, key)
    cond_by_id = {c.get("서비스ID"): c for c in conditions}

    policies = [p for p in (to_schema(s, cond_by_id.get(s.get("서비스ID")))
                            for s in services) if p["name"]]
    if not policies:
        print("⚠️ 수집 결과가 0건입니다. 기존 파일을 보존하고 종료합니다.")
        sys.exit(1)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(policies, f, ensure_ascii=False, indent=2)
    print(f"완료: {len(policies)}건 → {OUT_PATH}")


if __name__ == "__main__":
    main()
