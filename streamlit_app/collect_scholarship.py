# -*- coding: utf-8 -*-
"""
한국장학재단 학자금지원정보 수집기 (확장, odcloud)

  GET https://api.odcloud.kr/api/15028252/v1/{uddi}   (대학생 학자금, 약 1,600건)
  params: page, perPage, returnType=JSON, serviceKey
  필드(한글 키): 번호, 운영기관명, 상품명, 상품구분, 학자금유형구분, 성적기준,
                소득기준, 지원금액, 지역거주여부, 신청기간, 제출서류

  ⚠️ 소득기준이 "학자금 지원구간 N구간"이라 중위소득%와 척도가 다름
     → income_max_pct=null 로 두고 체크리스트 안내용 텍스트만 유지

사용:
  python collect_scholarship.py --demo
  set ODCLOUD_API_KEY=...
  set SCHOLARSHIP_UDDI=uddi:xxxx   (data.go.kr 활용신청 후 상세페이지의 UDDI)
  python collect_scholarship.py
"""
import argparse
import json
import os
import re
import sys

BASE_URL = "https://api.odcloud.kr/api/15028252/v1/"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(BASE_DIR, "data", "scholarship.json")

SIDO_NAMES = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
              "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]


def map_category(row):
    t = str(row.get("학자금유형구분", "")) + str(row.get("상품구분", ""))
    return "교육·장학"   # 학자금 데이터는 전부 교육·장학 (대출성 상품도 학자금)


def parse_amount(text):
    """'등록금 전액', '연 300만원 이내' 등 → 최댓값(원)"""
    text = str(text or "")
    amounts = []
    for m in re.finditer(r"([\d,.]+)\s*억", text):
        try:
            amounts.append(int(float(m.group(1).replace(",", "")) * 100_000_000))
        except ValueError:
            pass
    for m in re.finditer(r"([\d,]+)\s*만\s*원", text):
        try:
            amounts.append(int(m.group(1).replace(",", "")) * 10_000)
        except ValueError:
            pass
    if not amounts:
        return None, text[:40] if text else ""
    best = max(amounts)
    if best >= 1_000_000_000:      # 사업 총예산 오파싱 방지
        return None, ""
    label = (f"최대 {best / 100_000_000:.1f}억원".replace(".0억", "억")
             if best >= 100_000_000 else f"최대 {best // 10_000:,}만원")
    return best, label


def parse_period(text):
    """'2024.5.21.~2024.6.20.' / '연중' → (start, end)"""
    text = str(text or "")
    if not text or any(k in text for k in ("연중", "상시", "수시")):
        return "", "상시"
    dates = re.findall(r"(\d{4})[.\-/년\s]*(\d{1,2})[.\-/월\s]*(\d{1,2})", text)
    fmt = lambda d: f"{d[0]}.{int(d[1]):02d}.{int(d[2]):02d}"
    if len(dates) >= 2:
        return fmt(dates[0]), fmt(dates[-1])
    if len(dates) == 1:
        return "", fmt(dates[0])
    return "", "상시"


def map_region(text):
    """지역거주여부 텍스트에서 시도 추출. 없으면 전국."""
    text = str(text or "")
    if not text or "무관" in text or "해당없음" in text:
        return ["전국"]
    found = [s for s in SIDO_NAMES if s in text]
    return found if found else ["전국"]


GENERIC_NAMES = {"장학금", "장학생", "장학", "특별장학생", "일반장학생", "정기장학생"}


def parse_income_pct(text):
    """'기준 중위소득 100% 이하' → 100. '학자금 지원구간 N구간'은 척도가 달라 null."""
    m = re.search(r"중위\s*소득\s*(\d+)\s*%", str(text or ""))
    return int(m.group(1)) if m else None


def to_schema(row):
    """※ 실제 API 필드명 기준 (2026-07 실호출로 확인):
    상품명/운영기관명/홈페이지 주소/모집시작일/모집종료일/지원내역 상세내용/
    지역거주여부 상세내용/소득기준 상세내용/성적기준 상세내용 ..."""
    support_txt = str(row.get("지원내역 상세내용", "") or "")
    amount, label = parse_amount(support_txt)
    if not label and "등록금 전액" in support_txt:
        label = "등록금 전액"

    def fmt_date(v):
        m = re.search(r"(\d{4})[.\-/]?(\d{1,2})[.\-/]?(\d{1,2})", str(v or ""))
        return f"{m.group(1)}.{int(m.group(2)):02d}.{int(m.group(3)):02d}" if m else ""
    start = fmt_date(row.get("모집시작일"))
    end = fmt_date(row.get("모집종료일")) or "상시"

    org = (row.get("운영기관명") or "").strip()
    name = (row.get("상품명") or "").strip()
    # '장학생'·'장학금' 같은 범용 상품명은 운영기관을 붙여 구분 (병합 시 오중복 방지)
    if name in GENERIC_NAMES or len(name) <= 4:
        name = f"{org} {name}".strip()

    url = str(row.get("홈페이지 주소", "") or "").strip()
    url = re.sub(r"^(https?://)+(?=https?://)", "", url)   # 'http://http://…' 오타 교정
    # 'http//'·'https:'·'http;//' 같은 오타 스킴 정규화
    url = re.sub(r"^(https?)(?=[:;/])[:;]?/{0,2}(?!/)",
                 lambda m: m.group(1).lower() + "://", url, flags=re.I)
    if " " in url:
        url = url.split()[0]
    if re.search(r"[가-힣]", url) or "." not in url:
        url = ""
    elif not url.startswith("http"):
        url = "https://" + url

    income_txt = str(row.get("소득기준 상세내용", "") or "").replace("○", " ").strip()
    grade_txt = str(row.get("성적기준 상세내용", "") or "").replace("○", " ").strip()

    # 특정자격(종교·특정대학·추천 필요 등) — 일반 사용자에게 경고 표시용
    special_bits = []
    for field in ("특정자격 상세내용", "자격제한 상세내용"):
        v = str(row.get(field, "") or "").replace("○", " ").strip()
        if v and not any(k in v for k in ("해당없음", "제한없음", "없음")):
            special_bits.append(v)
    special_req = " / ".join(special_bits)[:80]
    summary_bits = [b for b in [
        f"{org} {row.get('상품구분', '')}".strip(),
        support_txt.replace("○", " ").strip(),
        f"소득: {income_txt}" if income_txt else "",
    ] if b]
    summary = " / ".join(summary_bits)
    if len(summary) > 120:
        summary = summary[:117] + "..."

    return {
        "id": f"SC-{row.get('번호', '')}",
        "name": name,
        "category": map_category(row),
        "org": org,
        "summary": summary,
        "amount_max": amount,
        "amount_label": label,
        "apply_start": start,
        "apply_end": end,
        "url": url,
        "special_req": special_req,
        "status_label": "신청 가능",
        "benefit_score": min(1.0, 0.3 + (amount or 0) / 10_000_000 * 0.7) if amount else 0.5,
        "keywords": ["장학금", "학자금", "등록금"]
                    + [w for w in re.findall(r"[가-힣]{2,}", row.get("상품명", ""))][:4],
        "eligibility": {
            "age_min": 0, "age_max": 200,
            "regions": map_region(row.get("지역거주여부 상세내용")),
            "income_max_pct": parse_income_pct(income_txt),
            "status": ["대학생"],
            "housing": [],
        },
    }


def fetch_all(service_key, uddi, per_page=500, max_pages=10):
    import requests
    rows, page = [], 1
    while page <= max_pages:
        r = requests.get(BASE_URL + uddi, params={
            "page": page, "perPage": per_page,
            "returnType": "JSON", "serviceKey": service_key,
        }, timeout=30)
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


# ── 데모용 원본 샘플 (실제 API 필드명 기준) ──────────────────
DEMO_RAW = [
    {
        "번호": 1, "운영기관명": "광주남구장학회", "상품명": "행복나눔 장학생",
        "상품구분": "장학금", "학자금유형구분": "생활비", "운영기관구분": "지자체(출자출연기관)",
        "성적기준 상세내용": "○ 제한 없음",
        "소득기준 상세내용": "○ 2024년도 기준 중위소득 100% 이하인 가구",
        "지원내역 상세내용": "○ 1인당 100만원※ 생활비 지원",
        "지역거주여부 상세내용": "○ 주민등록상 주소지가 광주광역시 남구로 1년 이상",
        "모집시작일": "2024-09-23", "모집종료일": "2024-10-11",
        "홈페이지 주소": "https://namgu.gwangju.kr",
    },
    {
        "번호": 2, "운영기관명": "재단법인 조준장학재단", "상품명": "장학생",
        "상품구분": "장학금", "학자금유형구분": "생활비", "운영기관구분": "기타",
        "성적기준 상세내용": "직전학기 3.0 이상",
        "소득기준 상세내용": "○ 24-2학기 학자금 지원구간 5구간 이내",
        "지원내역 상세내용": "○ 720만원 (생활비/연)",
        "지역거주여부 상세내용": "해당없음",
        "모집시작일": "2024-11-13", "모집종료일": "",
        "홈페이지 주소": "미정",
    },
]


def run_demo():
    print("[demo] 장학재단 매핑 검증 (키 불필요)")
    mapped = [to_schema(x) for x in DEMO_RAW]
    checks = [
        ("금액 파싱(지원내역 100만원)", mapped[0]["amount_max"] == 1_000_000,
         f"{mapped[0]['amount_max']:,}"),
        ("모집기간 파싱", (mapped[0]["apply_start"], mapped[0]["apply_end"])
         == ("2024.09.23", "2024.10.11"),
         f"{mapped[0]['apply_start']} ~ {mapped[0]['apply_end']}"),
        ("홈페이지 주소 → url", mapped[0]["url"] == "https://namgu.gwangju.kr",
         mapped[0]["url"]),
        ("중위소득 100% 파싱", mapped[0]["eligibility"]["income_max_pct"] == 100,
         str(mapped[0]["eligibility"]["income_max_pct"])),
        ("광주광역시 남구 → 광주", mapped[0]["eligibility"]["regions"] == ["광주"],
         str(mapped[0]["eligibility"]["regions"])),
        ("범용 상품명 → 기관명 접두", mapped[1]["name"] == "재단법인 조준장학재단 장학생",
         mapped[1]["name"]),
        ("지원구간 → income null", mapped[1]["eligibility"]["income_max_pct"] is None,
         str(mapped[1]["eligibility"]["income_max_pct"])),
        ("해당없음 → 전국", mapped[1]["eligibility"]["regions"] == ["전국"],
         str(mapped[1]["eligibility"]["regions"])),
        ("빈 종료일 → 상시", mapped[1]["apply_end"] == "상시", mapped[1]["apply_end"]),
        ("http 아닌 값 → url 제거", mapped[1]["url"] == "", repr(mapped[1]["url"])),
        ("대학생 status 부여", mapped[0]["eligibility"]["status"] == ["대학생"],
         str(mapped[0]["eligibility"]["status"])),
        ("카테고리 교육·장학", mapped[0]["category"] == "교육·장학", mapped[0]["category"]),
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
    ap = argparse.ArgumentParser(description="한국장학재단 학자금지원정보 수집기")
    ap.add_argument("--demo", action="store_true", help="키 없이 매핑 검증")
    args = ap.parse_args()

    if args.demo:
        sys.exit(run_demo())

    import keys as keyloader
    key = keyloader.get_key("ODCLOUD_API_KEY")
    # UDDI는 공개 데이터셋 식별자(비밀 아님) — 변경 시 .env의 SCHOLARSHIP_UDDI로 교체
    # 기본값 = 2026-06-15 갱신본 (구버전 ccd5ddd5…는 2024년 스냅샷이라 전부 마감 상태)
    uddi = keyloader.get_key("SCHOLARSHIP_UDDI") or "uddi:16645324-7d91-4a1e-a603-a0f2e0029cbb"
    if not key:
        print("환경변수 ODCLOUD_API_KEY가 없습니다. (data.go.kr 개인 인증키)\n"
              "  키 없이 매핑만 확인하려면: python collect_scholarship.py --demo")
        sys.exit(1)

    print("장학재단 학자금지원정보 수집...")
    raw = fetch_all(key, uddi)
    policies = [p for p in (to_schema(x) for x in raw) if p["name"]]
    if not policies:
        print("⚠️ 수집 결과가 0건입니다. 기존 파일을 보존하고 종료합니다.")
        sys.exit(1)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(policies, f, ensure_ascii=False, indent=2)
    print(f"완료: {len(policies)}건 → {OUT_PATH}")


if __name__ == "__main__":
    main()
