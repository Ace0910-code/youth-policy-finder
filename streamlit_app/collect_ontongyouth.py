# -*- coding: utf-8 -*-
"""
온통청년 청년정책 수집기 (★핵심)

  GET https://www.youthcenter.go.kr/go/ythip/getPlcy
  params: apiKeyNm(전용키), pageNum, pageSize, rtnType=json
  응답: result.youthPolicyList[], result.pagging

주의(실호출로 검증된 함정):
  - 지역은 반드시 zipCd(법정동코드 앞 2자리→시도)로 매핑. 비면 "전국".
    등록기관명으로 추정하면 중앙부처 정책이 엉뚱한 지역으로 오분류된다.
  - 금액은 plcySprtCn에서 억/만원을 모두 찾아 '최댓값' 사용.
  - sprtTrgtMaxAge가 0/공백이면 연령 무관(0~200).

사용:
  python collect_ontongyouth.py --demo          # 키 없이 매핑 로직 검증
  set ONTONG_API_KEY=... && python collect_ontongyouth.py
"""
import argparse
import json
import os
import re
import sys

API_URL = "https://www.youthcenter.go.kr/go/ythip/getPlcy"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(BASE_DIR, "data", "ontongyouth.json")

# 법정동코드 앞 2자리 → 시도
ZIP_SIDO = {
    "11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주",
    "30": "대전", "31": "울산", "36": "세종", "41": "경기", "42": "강원",
    "51": "강원", "43": "충북", "44": "충남", "45": "전북", "52": "전북",
    "46": "전남", "47": "경북", "48": "경남", "50": "제주",
}

CATEGORY_MAP = {
    "일자리": "취업·창업", "주거": "주거", "교육": "교육·역량",
    "복지문화": "생활·교통", "참여권리": "생활·교통",
}


# 시·군명 → 시도 (기관명·정책명에 '광양시'처럼 시군만 적힌 경우의 최종 폴백)
# ※ 전국에 이름이 중복되는 고성군(강원/경남)·광주시(경기/광역시 혼동)는 제외
_SIG = {
    "경기": "수원시 성남시 고양시 용인시 부천시 안산시 안양시 남양주시 화성시 평택시 "
            "의정부시 시흥시 파주시 김포시 광명시 군포시 오산시 이천시 양주시 안성시 "
            "구리시 포천시 의왕시 하남시 여주시 동두천시 과천시 양평군 가평군 연천군",
    "강원": "춘천시 원주시 강릉시 동해시 태백시 속초시 삼척시 홍천군 횡성군 영월군 "
            "평창군 정선군 철원군 화천군 양구군 인제군 양양군",
    "충북": "청주시 충주시 제천시 보은군 옥천군 영동군 증평군 진천군 괴산군 음성군 단양군",
    "충남": "천안시 공주시 보령시 아산시 서산시 논산시 계룡시 당진시 금산군 부여군 "
            "서천군 청양군 홍성군 예산군 태안군",
    "전북": "전주시 군산시 익산시 정읍시 남원시 김제시 완주군 진안군 무주군 장수군 "
            "임실군 순창군 고창군 부안군",
    "전남": "목포시 여수시 순천시 나주시 광양시 담양군 곡성군 구례군 고흥군 보성군 "
            "화순군 장흥군 강진군 해남군 영암군 무안군 함평군 영광군 장성군 완도군 "
            "진도군 신안군",
    "경북": "포항시 경주시 김천시 안동시 구미시 영주시 영천시 상주시 문경시 경산시 "
            "군위군 의성군 청송군 영양군 영덕군 청도군 고령군 성주군 칠곡군 예천군 "
            "봉화군 울진군 울릉군",
    "경남": "창원시 진주시 통영시 사천시 김해시 밀양시 거제시 양산시 의령군 함안군 "
            "창녕군 남해군 하동군 산청군 함양군 거창군 합천군",
    "제주": "제주시 서귀포시",
}
SIGUNGU_SIDO = {name: sido for sido, names in _SIG.items() for name in names.split()}


# 주관기관명 → 시도 (zipCd가 빈 지자체 정책 전용 폴백. 긴 이름부터 검사)
ORG_SIDO_FULL = [
    ("전남광주통합특별시", ["전남", "광주"]),      # 행정통합 명칭
    ("서울특별시", ["서울"]), ("부산광역시", ["부산"]), ("대구광역시", ["대구"]),
    ("인천광역시", ["인천"]), ("광주광역시", ["광주"]), ("대전광역시", ["대전"]),
    ("울산광역시", ["울산"]), ("세종특별자치시", ["세종"]), ("경기도", ["경기"]),
    ("강원특별자치도", ["강원"]), ("강원도", ["강원"]), ("충청북도", ["충북"]),
    ("충청남도", ["충남"]), ("전북특별자치도", ["전북"]), ("전라북도", ["전북"]),
    ("전라남도", ["전남"]), ("경상북도", ["경북"]), ("경상남도", ["경남"]),
    ("제주특별자치도", ["제주"]), ("제주도", ["제주"]),
]


def _org_region(org_name, policy_name=""):
    """주관기관명(±정책명)에서 시도 판별. 중앙부처(부/처/청/위원회)나 단서 없음 → None."""
    org = str(org_name or "").strip()
    if not org or re.search(r"(부|처|청|위원회)$", org):
        return None
    for full, sidos in ORG_SIDO_FULL:
        if full in org:
            return list(sidos)
    text = org + " " + str(policy_name or "")
    for sig, sido in SIGUNGU_SIDO.items():      # '광양시 청년센터', '(김천시) …'
        if sig in text:
            return [sido]
    return None


def map_region(zip_cd, org_name="", policy_name=""):
    """zipCd(콤마 구분 법정동코드들) → 시도 리스트.
    ① zipCd의 시도 코드가 1~9개면 그대로 사용
    ② zipCd가 '사실상 전국'(10개 시도 이상)이어도 주관기관이 지자체로 판별되면
       지자체 우선 — 기초지자체 부서가 주관하는 정책이 전국 대상인 경우는 없어서,
       zipCd에 전 시도가 잘못 등록된 사례(예: 광양시 청년복합공간)를 걸러낸다
    ③ zipCd가 비거나 미지 접두어(행정개편 신설 코드)면 기관명·정책명 폴백 → 전국"""
    org_reg = _org_region(org_name, policy_name)
    if zip_cd and str(zip_cd).strip():
        sidos = []
        for code in re.split(r"[,\s]+", str(zip_cd).strip()):
            sido = ZIP_SIDO.get(code[:2])
            if sido and sido not in sidos:
                sidos.append(sido)
        if len(sidos) >= 10:                   # 사실상 전국 표기
            return org_reg or ["전국"]
        if sidos:
            return sidos
        # 코드는 있는데 전부 미지 접두어 → 기관명 폴백으로 진행
    return org_reg or ["전국"]


def clean_summary(text):
    """'ㅇ (목적) … ㅇ (주요내용) …' 개조식 원문 → 한 줄 요약
    (주요내용/지원내용 우선, 없으면 목적, 없으면 라벨 괄호 제거)"""
    t = re.sub(r"[ㅇo○□◦▪•·]+\s*", " ", str(text or ""))
    m = (re.search(r"\((?:주요\s*내용|지원\s*내용|사업\s*내용)\)\s*(.+?)(?=\([가-힣\s]{1,7}\)|$)", t)
         or re.search(r"\(목\s*적\)\s*(.+?)(?=\([가-힣\s]{1,7}\)|$)", t))
    if m:
        t = m.group(1)
    else:
        t = re.sub(r"\([가-힣\s]{1,7}\)", " ", t)
    return re.sub(r"\s+", " ", t).strip(" -–·,") or str(text or "")


def clean_url(u):
    """URL 정제: 이중 스킴 오타·공백·비URL 텍스트('전화문의' 등) 방어, 스킴 보정"""
    u = str(u or "").strip()
    u = re.sub(r"^(https?://)+(?=https?://)", "", u)
    # 'http//'·'https:'·'http;//' 같은 오타 스킴 정규화
    u = re.sub(r"^(https?)(?=[:;/])[:;]?/{0,2}(?!/)",
               lambda m: m.group(1).lower() + "://", u, flags=re.I)
    if " " in u:
        u = u.split()[0]
    if not u or re.search(r"[가-힣]", u) or "." not in u:
        return ""
    if not u.startswith("http"):
        u = "https://" + u
    return u


DETAIL_URL = "https://www.youthcenter.go.kr/youthPolicy/ythPlcyTotalSearch/ythPlcyDetail/{}"
_HOME_PATHS = {"", "ko", "kr", "index", "main", "index.do", "main.do",
               "index.jsp", "main.jsp", "index.html", "main.html", "index.php"}


def is_specific_url(u):
    """기관 홈페이지 메인(경로 없는 도메인)이면 False — 정책 안내로 부적절"""
    if not u:
        return False
    from urllib.parse import urlparse
    p = urlparse(u)
    return bool(p.query) or p.path.strip("/").lower() not in _HOME_PATHS


def best_url(aply, ref, plcy_no):
    """신청링크 → 참고링크 순으로 '구체적인' URL을 고르고,
    없거나 홈페이지 메인뿐이면 온통청년 정책 상세 페이지로 보증 연결"""
    for u in (clean_url(aply), clean_url(ref)):
        if is_specific_url(u):
            return u
    return DETAIL_URL.format(plcy_no) if plcy_no else (clean_url(aply) or clean_url(ref))


def parse_amount(text):
    """지원내용 텍스트에서 억/만원을 모두 찾아 최댓값(원)을 반환.
    첫 매치만 쓰면 '월 20만원…최대 240만원'에서 20만원이 잡히므로 반드시 전부 스캔.
    10억 이상은 개인 지원금이 아니라 사업 총예산일 가능성이 높아 금액 미상 처리."""
    if not text:
        return None, ""
    amounts = []
    for m in re.finditer(r"([\d,.]+)\s*억(?:\s*([\d,]+)\s*만\s*원)?", text):
        try:
            v = float(m.group(1).replace(",", "")) * 100_000_000
            if m.group(2):
                v += int(m.group(2).replace(",", "")) * 10_000
            amounts.append(int(v))
        except ValueError:
            pass
    for m in re.finditer(r"([\d,]+)\s*만\s*원", text):
        try:
            amounts.append(int(m.group(1).replace(",", "")) * 10_000)
        except ValueError:
            pass
    if not amounts:
        return None, ""
    best = max(amounts)
    if best >= 1_000_000_000:      # 사업 총예산 오파싱 방지
        return None, ""
    if best >= 100_000_000:
        label = f"최대 {best / 100_000_000:.1f}억원".replace(".0억", "억")
    else:
        label = f"최대 {best // 10_000:,}만원"
    return best, label


def parse_age(raw_min, raw_max):
    """sprtTrgtMaxAge 0/공백 → 연령 무관(0~200)"""
    try:
        a_min = int(raw_min) if str(raw_min).strip() else 0
    except (ValueError, TypeError):
        a_min = 0
    try:
        a_max = int(raw_max) if str(raw_max).strip() else 0
    except (ValueError, TypeError):
        a_max = 0
    if a_max <= 0:
        return 0, 200
    return a_min, a_max


def parse_apply_period(aply_ymd):
    """'20240701 ~ 20240831' / '상시' → (start, end)"""
    if not aply_ymd or "상시" in str(aply_ymd):
        return "", "상시"
    dates = re.findall(r"(\d{4})[.\-/]?(\d{2})[.\-/]?(\d{2})", str(aply_ymd))
    fmt = lambda d: f"{d[0]}.{d[1]}.{d[2]}"
    if len(dates) >= 2:
        return fmt(dates[0]), fmt(dates[1])
    if len(dates) == 1:
        return fmt(dates[0]), "상시"
    return "", "상시"


def to_schema(item):
    """온통청년 원본 1건 → 공통 스키마"""
    support_text = item.get("plcySprtCn", "") or ""
    amount, label = parse_amount(support_text)
    a_min, a_max = parse_age(item.get("sprtTrgtMinAge"), item.get("sprtTrgtMaxAge"))
    start, end = parse_apply_period(item.get("aplyYmd"))
    if start and end not in ("", "상시") and end < start:   # 원본 연도 오타 → 확인 필요 처리
        end = "상시"
    qlfc = item.get("addAplyQlfcCndCn", "") or ""
    keywords = [k.strip() for k in str(item.get("plcyKywdNm", "")).split(",") if k.strip()]

    summary = clean_summary((item.get("plcyExplnCn") or support_text or "")
                            .strip().replace("\n", " "))
    if len(summary) > 120:
        summary = summary[:117] + "..."

    # 특정 집단 전용 정책 감지 (자유텍스트 자격요건) — 일반 사용자에게 경고 표시용
    special_req = ""
    if any(k in qlfc for k in ("자립준비", "보호종료", "한부모", "다문화", "북한이탈",
                               "장애인", "국가유공", "기초생활", "차상위", "농업인",
                               "예술인", "군인", "제대군인")):
        special_req = qlfc.strip().replace("\n", " ")[:80]

    return {
        "id": f"OY-{item.get('plcyNo', '')}",
        "name": (item.get("plcyNm") or "").strip(),
        "category": CATEGORY_MAP.get(str(item.get("lclsfNm", "")).strip(), "생활·교통"),
        "org": (item.get("sprvsnInstCdNm") or "").strip(),
        "summary": summary,
        "amount_max": amount,
        "amount_label": label,
        "apply_start": start,
        "apply_end": end,
        "url": best_url(item.get("aplyUrlAddr"), item.get("refUrlAddr1"),
                        item.get("plcyNo")),
        "special_req": special_req,
        "status_label": "신청 가능",
        "benefit_score": min(1.0, 0.2 + (amount or 0) / 10_000_000 * 0.8) if amount else 0.3,
        "keywords": keywords[:8],
        "eligibility": {
            "age_min": a_min, "age_max": a_max,
            "regions": map_region(item.get("zipCd"), item.get("sprvsnInstCdNm"),
                                  item.get("plcyNm")),
            "income_max_pct": None,          # earnMaxAmt는 %척도가 아니므로 미사용
            "status": [],
            "housing": ["무주택"] if "무주택" in qlfc else [],
        },
    }


def fetch_all(api_key, page_size=100, max_pages=50):
    import time
    import requests
    items, page = [], 1
    while page <= max_pages:
        # 일시적 400/5xx 대비 재시도 (간헐적으로 발생 — 실패 시 수집분만이라도 저장)
        r = None
        for attempt in range(4):
            try:
                r = requests.get(API_URL, params={
                    "apiKeyNm": api_key, "pageNum": page,
                    "pageSize": page_size, "rtnType": "json",
                }, timeout=30)
                r.raise_for_status()
                break
            except requests.exceptions.RequestException as ex:
                if attempt == 3:
                    print(f"  ⚠️ page {page} 4회 실패({ex}) — 수집분 {len(items)}건으로 계속")
                    return items
                wait = 3 * (attempt + 1)
                print(f"  page {page} 재시도 {attempt + 1}/3 ({wait}s 대기)")
                time.sleep(wait)
        result = r.json().get("result", {})
        batch = result.get("youthPolicyList", []) or []
        if page == 1 and not batch:     # 한도 소진 시 200 + 오류 본문이 오는 경우 진단
            print(f"  ⚠️ 1페이지 응답에 정책이 없습니다. 응답: {r.text[:200]}")
        items.extend(batch)
        paging = result.get("pagging", {}) or {}
        total = int(paging.get("totCount", 0) or 0)
        print(f"  page {page}: {len(batch)}건 (누적 {len(items)}/{total})")
        if not batch or len(items) >= total:
            break
        page += 1
    return items


# ── 데모용 원본 샘플 (함정 케이스 포함) ──────────────────────
DEMO_RAW = [
    {   # 함정 1: 금액 다중 매치 → 240만원이 잡혀야 함 / zipCd 빈값 → 전국
        "plcyNo": "R2024000001", "plcyNm": "청년월세 한시 특별지원",
        "plcyExplnCn": "경제적 어려움을 겪는 청년층의 주거비 부담 경감을 위해 월세를 지원",
        "lclsfNm": "주거", "mclsfNm": "주거비지원", "plcyKywdNm": "월세,주거,청년",
        "plcySprtCn": "월 20만원씩 12개월간 분할 지급, 최대 240만원 지원",
        "sprvsnInstCdNm": "국토교통부", "aplyYmd": "20240226 ~ 상시",
        "aplyUrlAddr": "https://www.bokjiro.go.kr",
        "sprtTrgtMinAge": "19", "sprtTrgtMaxAge": "34", "zipCd": "",
        "addAplyQlfcCndCn": "무주택 청년, 부모와 별도 거주",
    },
    {   # 함정 2: zipCd 서울(11xxx) → 서울로만 매핑돼야 함
        "plcyNo": "R2024000002", "plcyNm": "서울 청년수당",
        "plcyExplnCn": "미취업 청년의 구직활동을 지원하는 수당",
        "lclsfNm": "일자리", "mclsfNm": "취업지원", "plcyKywdNm": "수당,구직,취업",
        "plcySprtCn": "월 50만원, 최대 6개월(총 300만원) 지급",
        "sprvsnInstCdNm": "서울특별시", "aplyYmd": "20240311 ~ 20240318",
        "aplyUrlAddr": "https://youth.seoul.go.kr",
        "sprtTrgtMinAge": "19", "sprtTrgtMaxAge": "34",
        "zipCd": "11110,11140,11170,11200,11215",
        "addAplyQlfcCndCn": "서울 거주 미취업 청년",
    },
    {   # 함정 3: zipCd 없는 지자체 정책 → 주관기관명 폴백으로 시도 매핑
        "plcyNo": "R2024000004", "plcyNm": "강진품애 청년 주거비 지원",
        "plcyExplnCn": "강진군 거주 청년의 주거비를 지원",
        "lclsfNm": "주거", "mclsfNm": "주거비지원", "plcyKywdNm": "월세,주거",
        "plcySprtCn": "월 10만원 주거비 지원",
        "sprvsnInstCdNm": "전남광주통합특별시 강진군 인구정책과",
        "aplyYmd": "상시", "aplyUrlAddr": "",
        "sprtTrgtMinAge": "19", "sprtTrgtMaxAge": "45", "zipCd": "",
        "addAplyQlfcCndCn": "",
    },
    {   # 함정 4: sprtTrgtMaxAge=0 → 연령 무관(0~200) / 억 단위 금액
        "plcyNo": "R2024000003", "plcyNm": "청년창업사관학교",
        "plcyExplnCn": "유망 창업 아이템 보유 청년 창업자를 발굴하여 사업화 지원",
        "lclsfNm": "일자리", "mclsfNm": "창업지원", "plcyKywdNm": "창업,스타트업",
        "plcySprtCn": "사업화 자금 최대 1억원 및 창업공간 지원",
        "sprvsnInstCdNm": "중소벤처기업부", "aplyYmd": "20240201 ~ 20240229",
        "aplyUrlAddr": "https://start.kosmes.or.kr",
        "sprtTrgtMinAge": "", "sprtTrgtMaxAge": "0", "zipCd": "",
        "addAplyQlfcCndCn": "",
    },
]


def run_demo():
    print("[demo] 온통청년 매핑 검증 (키 불필요)")
    ok = True
    mapped = [to_schema(x) for x in DEMO_RAW]

    checks = [
        ("금액 최댓값 선택", mapped[0]["amount_max"] == 2_400_000,
         f"기대 2,400,000 / 실제 {mapped[0]['amount_max']:,}"),
        ("빈 zipCd → 전국", mapped[0]["eligibility"]["regions"] == ["전국"],
         str(mapped[0]["eligibility"]["regions"])),
        ("무주택 텍스트 감지", mapped[0]["eligibility"]["housing"] == ["무주택"],
         str(mapped[0]["eligibility"]["housing"])),
        ("zipCd 11xxx → 서울", mapped[1]["eligibility"]["regions"] == ["서울"],
         str(mapped[1]["eligibility"]["regions"])),
        ("신청기간 파싱", mapped[1]["apply_end"] == "2024.03.18", mapped[1]["apply_end"]),
        ("빈 zipCd + 지자체 기관명 → 시도 폴백",
         mapped[2]["eligibility"]["regions"] == ["전남", "광주"],
         str(mapped[2]["eligibility"]["regions"])),
        ("정책명의 시·군명 → 시도 폴백",
         map_region("", "광양시청년센터", "(광양시) 청년복합공간 운영") == ["전남"],
         str(map_region("", "광양시청년센터", "(광양시) 청년복합공간 운영"))),
        ("zipCd 전국 오등록 + 지자체 주관 → 지자체 우선",
         map_region("11110,26110,27110,28110,29110,30110,31110,36110,41110,43110,44110",
                    "전남광주통합특별시 광양시 미래산업국") == ["전남", "광주"],
         str(map_region("11110,26110,27110,28110,29110,30110,31110,36110,41110,43110,44110",
                        "전남광주통합특별시 광양시 미래산업국"))),
        ("zipCd 전국 + 중앙부처 → 전국 유지",
         map_region("11110,26110,27110,28110,29110,30110,31110,36110,41110,43110,44110",
                    "국토교통부") == ["전국"],
         str(map_region("11110,26110,27110,28110,29110,30110,31110,36110,41110,43110,44110",
                        "국토교통부"))),
        ("시·군 단서 없으면 전국 유지",
         map_region("", "청년재단", "청년 도전 프로그램") == ["전국"],
         str(map_region("", "청년재단", "청년 도전 프로그램"))),
        ("maxAge=0 → 연령무관", (mapped[3]["eligibility"]["age_min"],
                                mapped[3]["eligibility"]["age_max"]) == (0, 200),
         f"{mapped[3]['eligibility']['age_min']}~{mapped[3]['eligibility']['age_max']}"),
        ("억 단위 금액", mapped[3]["amount_max"] == 100_000_000,
         f"{mapped[3]['amount_max']:,}"),
        ("카테고리 매핑", mapped[3]["category"] == "취업·창업", mapped[3]["category"]),
    ]
    for name, passed, detail in checks:
        print(f"  {'✅' if passed else '❌'} {name}: {detail}")
        ok &= passed
    print(f"[demo] {'모든 검증 통과' if ok else '검증 실패 항목 있음'} "
          f"({sum(1 for _, p, _ in checks if p)}/{len(checks)})")
    return 0 if ok else 1


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="온통청년 청년정책 수집기")
    ap.add_argument("--demo", action="store_true", help="키 없이 매핑 검증")
    ap.add_argument("--max-pages", type=int, default=50)
    args = ap.parse_args()

    if args.demo:
        sys.exit(run_demo())

    import keys
    api_key = keys.get_key("ONTONG_API_KEY")
    if api_key and not re.fullmatch(r"[0-9a-fA-F-]{36}", api_key):
        print(f"⚠️ ONTONG_API_KEY가 온통청년 전용키(UUID 형식)가 아닙니다 "
              f"(길이 {len(api_key)}). data.go.kr 키와 뒤바뀌지 않았는지 "
              f".env를 확인하세요. (python keys.py 로 현황 확인)")
        sys.exit(1)
    if not api_key:
        print("환경변수 ONTONG_API_KEY가 없습니다. (온통청년 전용키 필요)\n"
              "  발급: https://www.youthcenter.go.kr → 오픈API\n"
              "  키 없이 매핑만 확인하려면: python collect_ontongyouth.py --demo")
        sys.exit(1)

    print("온통청년 정책 수집 시작...")
    raw = fetch_all(api_key, max_pages=args.max_pages)
    policies = [p for p in (to_schema(x) for x in raw) if p["name"]]
    if not policies:
        # 일일 호출 한도 소진 등으로 0건이면 기존 수집분을 절대 덮어쓰지 않는다
        print("⚠️ 수집 결과가 0건입니다 (일일 호출 한도 소진 가능성). "
              "기존 파일을 보존하고 종료합니다.")
        sys.exit(1)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(policies, f, ensure_ascii=False, indent=2)
    print(f"완료: {len(policies)}건 → {OUT_PATH}")


if __name__ == "__main__":
    main()
