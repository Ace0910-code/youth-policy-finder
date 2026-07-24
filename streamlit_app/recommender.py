# -*- coding: utf-8 -*-
"""
「눈 떠보니 지원 대상이었습니다」 하이브리드 추천 엔진

구조 (LLM은 자격 판정에 절대 관여하지 않는다):
  1) 규칙 기반 자격 필터  : 나이·지역·소득·직업상태·주거 + 마감일 — 결정론적 판정
  2) 의미 기반 관심분야 매칭 : ko-sBERT(jhgan/ko-sroberta-multitask) cosine similarity
                              (모델이 없으면 키워드 규칙으로 자동 폴백, 임베딩은 캐싱)
  3) 가중 스코어 순위화     : 신청가능성 0.40 / 관심분야 0.25 / 지원효과 0.15
                              / 마감임박 0.10 / 실행가능성 0.10  → 적합도(%)
  4) 설명 생성             : 추천 이유·AI 한줄 요약·신청 전 체크리스트 (설명 전용)

단독 실행:  python recommender.py
"""
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DEFAULT_DATA = os.path.join(DATA_DIR, "policies.json")
REAL_DATA = os.path.join(DATA_DIR, "policies_real.json")

# 가중치 (합 = 1.0)
# 제안서의 예시값(0.40/0.25/0.15/0.10/0.10)에서 출발해 페르소나 검증으로 조정:
# 실데이터(3,546건)에서 고액 대출 상품이 관심분야와 무관하게 상위를 점령하는
# 문제가 확인되어 관심분야 가중을 높이고 지원효과·실행가능성을 낮췄다.
WEIGHTS = {
    "eligibility": 0.40,   # 신청가능성
    "interest":    0.35,   # 관심분야 일치 (0.25 → 0.35)
    "benefit":     0.10,   # 지원효과 (0.15 → 0.10)
    "deadline":    0.10,   # 마감임박(긴급도)
    "feasibility": 0.05,   # 실행가능성 (0.10 → 0.05)
}

# 총 지원 규모 추정에서 제외할 항목 (과대추정 방지)
EXCLUDE_FROM_TOTAL_KEYWORDS = ("대출", "융자", "자산형성", "창업", "사업화", "보증")
EXCLUDE_FROM_TOTAL_CAP = 15_000_000  # 1,500만원 초과 상한은 합산 제외


# ──────────────────────────────────────────────
# 날짜 유틸
# ──────────────────────────────────────────────
def parse_date(s):
    """'2024.07.15' → date, '상시'/빈값 → None"""
    if not s:
        return None
    s = str(s).strip()
    if "상시" in s or s in ("", "-", "미정"):
        return None
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def days_left(policy, as_of):
    """마감까지 남은 일수. 상시=None, 마감 지남=음수."""
    end = parse_date(policy.get("apply_end"))
    if end is None:
        return None
    return (end - as_of).days


# ──────────────────────────────────────────────
# 데이터 로딩 (샘플/실데이터에 따라 기준일 자동 전환)
# ──────────────────────────────────────────────
def load_policies(path=None):
    """
    반환: (policies: list[dict], as_of: date)
    - 파일이 {"as_of": ..., "policies": [...]} 형태면 as_of를 기준일로 사용
      (샘플 데이터는 2024년 정책이므로 기준일을 함께 저장해 둠)
    - 리스트 형태(실데이터 수집 결과)면 오늘을 기준일로 사용
    """
    if path is None:
        path = REAL_DATA if os.path.exists(REAL_DATA) else DEFAULT_DATA
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict) and "policies" in raw:
        as_of = parse_date(raw.get("as_of")) or date.today()
        return raw["policies"], as_of
    return raw, date.today()


# ──────────────────────────────────────────────
# 사용자 프로필
# ──────────────────────────────────────────────
@dataclass
class UserProfile:
    name: str = "청년"
    age: int = 25
    region: str = "서울"           # 시도명
    status: str = "대학생"          # 대학생/대학원생/취업준비생/사회초년생/재직자/무직/자영업자/프리랜서/창업자
    school: str = ""
    housing: str = "무주택"         # 무주택/자가/기타
    income_pct: int | None = None   # 기준 중위소득 % (None=모름/입력 안 함)
    interests: list = field(default_factory=list)   # 관심분야 태그
    interest_text: str = ""         # 자유 텍스트

    def interest_query(self):
        parts = list(self.interests)
        if self.interest_text.strip():
            parts.append(self.interest_text.strip())
        return " ".join(parts) if parts else ""


# 직업상태 동의어 (정책 status 필드와 사용자 입력을 잇는 규칙)
STATUS_SYNONYMS = {
    "대학생": {"대학생"},
    "대학원생": {"대학원생", "대학생"},
    "취업준비생": {"취업준비생", "무직"},
    "사회초년생": {"사회초년생", "재직자"},
    "재직자": {"재직자"},
    "무직": {"무직", "취업준비생"},
    "자영업자": {"자영업자", "창업자"},
    "프리랜서": {"프리랜서", "자영업자"},
    "창업자": {"창업자", "자영업자"},
}


# ──────────────────────────────────────────────
# 1) 규칙 기반 자격 필터 (결정론적 — LLM 관여 없음)
# ──────────────────────────────────────────────
def check_eligibility(policy, user, as_of):
    """
    반환: (eligible: bool, matched: list[str], notes: list[str])
    matched = 확인된 자격 근거, notes = 사용자가 직접 확인해야 할 사항
    """
    e = policy.get("eligibility", {}) or {}
    matched, notes = [], []

    # 마감 지난 정책 제외
    d = days_left(policy, as_of)
    if d is not None and d < 0:
        return False, [], ["신청 기간이 종료된 정책"]

    # 나이
    age_min = e.get("age_min") or 0
    age_max = e.get("age_max") or 0
    if age_max in (0, None):        # 0/공백 = 연령 무관
        age_min, age_max = age_min or 0, 200
    if not (age_min <= user.age <= age_max):
        return False, [], []
    if (age_min, age_max) != (0, 200):
        matched.append(f"연령 {age_min}~{age_max}세 충족 (만 {user.age}세)")

    # 지역
    regions = e.get("regions") or ["전국"]
    if "전국" in regions:
        matched.append("전국 단위 정책")
    elif user.region in regions:
        matched.append(f"{user.region} 거주자 대상 충족")
    else:
        return False, [], []

    # 직업상태
    req_status = e.get("status") or []
    if req_status:
        user_set = STATUS_SYNONYMS.get(user.status, {user.status})
        if user_set & set(req_status):
            matched.append(f"대상 상태({'/'.join(req_status)}) 충족")
        else:
            return False, [], []

    # 주거
    req_housing = e.get("housing") or []
    if req_housing:
        if user.housing in req_housing:
            matched.append(f"{'/'.join(req_housing)} 요건 충족")
        else:
            return False, [], []

    # 소득 (모름이면 통과시키되 확인사항으로 안내)
    cap = e.get("income_max_pct")
    if cap is not None:
        if user.income_pct is None:
            notes.append(f"소득 요건: 기준 중위소득 {cap}% 이하 — 건강보험료 등으로 직접 확인 필요")
        elif user.income_pct <= cap:
            matched.append(f"소득 기준(중위소득 {cap}% 이하) 충족")
        else:
            return False, [], []

    return True, matched, notes


# ──────────────────────────────────────────────
# 2) 의미 기반 관심분야 매칭 (ko-sBERT → 키워드 폴백)
# ──────────────────────────────────────────────
CATEGORY_INTEREST_MAP = {
    "주거": {"주거·독립", "주거", "월세", "전세", "자취", "독립"},
    "취업·창업": {"취업·이직", "창업", "취업", "구직", "일자리", "이직"},
    "교육·장학": {"학비·장학금", "장학금", "등록금", "학비"},
    "교육·역량": {"자기계발·교육", "교육", "자격증", "어학", "코딩", "역량"},
    "생활·교통": {"생활비·교통", "자산형성", "생활비", "교통", "문화·여가", "문화", "저축"},
}


def _policy_text(p):
    return " ".join([p.get("name", ""), p.get("category", ""),
                     p.get("summary", ""), " ".join(p.get("keywords", []))])


class InterestMatcher:
    """정책 임베딩은 데이터 해시 기준으로 캐싱, 질의 임베딩은 인스턴스 내 캐싱."""

    def __init__(self, policies, use_embeddings=True, cache_dir=DATA_DIR, verbose=False):
        self.policies = policies
        self.mode = "keyword"
        self._query_cache = {}
        self._emb = None
        self._model = None
        if use_embeddings:
            try:
                self._init_embeddings(cache_dir, verbose)
                self.mode = "embedding"
            except Exception as ex:            # 모델 없음/로드 실패 → 키워드 폴백
                if verbose:
                    print(f"[matcher] 임베딩 사용 불가({type(ex).__name__}) → 키워드 매칭 폴백")

    def _init_embeddings(self, cache_dir, verbose):
        import hashlib
        import numpy as np
        from sentence_transformers import SentenceTransformer

        texts = [_policy_text(p) for p in self.policies]
        key = hashlib.md5("|".join(texts).encode("utf-8")).hexdigest()[:12]
        cache_path = os.path.join(cache_dir, f"emb_cache_{key}.npy")

        self._model = SentenceTransformer("jhgan/ko-sroberta-multitask")
        if os.path.exists(cache_path):
            self._emb = np.load(cache_path)
            if verbose:
                print(f"[matcher] 정책 임베딩 캐시 로드: {os.path.basename(cache_path)}")
        else:
            if verbose:
                print(f"[matcher] 정책 {len(texts)}건 임베딩 생성 중...")
            self._emb = self._model.encode(texts, normalize_embeddings=True,
                                           show_progress_bar=False)
            os.makedirs(cache_dir, exist_ok=True)
            np.save(cache_path, self._emb)

    def score(self, query):
        """질의 대비 각 정책의 관심분야 일치도 0~1 리스트."""
        if not query.strip():
            return [0.5] * len(self.policies)     # 관심분야 미입력 → 중립
        if self.mode == "embedding":
            return self._score_embedding(query)
        return self._score_keyword(query)

    def _score_embedding(self, query):
        import numpy as np
        if query not in self._query_cache:
            self._query_cache[query] = self._model.encode(
                [query], normalize_embeddings=True, show_progress_bar=False)[0]
        q = self._query_cache[query]
        sims = self._emb @ q                       # normalize됨 → 내적 = cosine
        # cosine(-1~1) → 0~1 구간으로 완만하게 정규화 (ko-sroberta는 대개 0.1~0.7 분포)
        return [float(min(1.0, max(0.0, (s - 0.05) / 0.55))) for s in sims]

    def _score_keyword(self, query):
        tokens = set(re.findall(r"[가-힣A-Za-z0-9]+", query))
        scores = []
        for p in self.policies:
            kw = set(p.get("keywords", [])) | {p.get("category", "")}
            hit = 0.0
            for t in tokens:
                if any(t in k or k in t for k in kw if k):
                    hit += 1.0
                elif t in p.get("summary", "") or t in p.get("name", ""):
                    hit += 0.5
            # 카테고리-관심 태그 매핑 보너스
            cat_terms = CATEGORY_INTEREST_MAP.get(p.get("category", ""), set())
            if any(t in ct or ct in t for t in tokens for ct in cat_terms):
                hit += 1.0
            scores.append(min(1.0, 0.25 + hit * 0.25) if hit else 0.2)
        return scores


# ──────────────────────────────────────────────
# 3) 가중 스코어 순위화
# ──────────────────────────────────────────────
def _eligibility_score(matched, notes, special=False):
    """확인된 자격 근거가 많고 미확인 항목이 적을수록 신청가능성↑.
    특정자격(종교·자립준비청년 등 규칙으로 판정 불가한 요건)은 신청가능성 불확실 → 감점."""
    s = 0.70 + 0.08 * len(matched) - 0.10 * len(notes)
    if special:
        s -= 0.30
    return min(1.0, max(0.15, s))


def _deadline_score(policy, as_of):
    d = days_left(policy, as_of)
    start = parse_date(policy.get("apply_start"))
    if start and start > as_of:
        return 0.15                     # 아직 접수 전
    if d is None:
        return 0.30                     # 상시
    if d <= 14:
        return 1.0
    if d <= 30:
        return 0.70
    if d <= 60:
        return 0.45
    return 0.20


def _feasibility_score(policy, as_of):
    s = 0.5
    if policy.get("url"):
        s += 0.25
    start = parse_date(policy.get("apply_start"))
    label = policy.get("status_label", "")
    if "심사" in label or (start and start > as_of):
        s -= 0.25
    elif "가능" in label or "상시" in str(policy.get("apply_end", "")):
        s += 0.25
    # 특정자격(종교재단·자립준비청년 등) 정책은 일반 사용자의 실행가능성이 낮음 → 순위 하향
    if policy.get("special_req"):
        s -= 0.3
    return min(1.0, max(0.1, s))


def is_deadline_soon(policy, as_of, within=7):
    d = days_left(policy, as_of)
    return d is not None and 0 <= d <= within


def get_collected_at(path=None):
    """데이터 수집 시각 문자열. 파일에 collected_at이 있으면 사용, 없으면 파일 수정시각."""
    if path is None:
        path = REAL_DATA if os.path.exists(REAL_DATA) else DEFAULT_DATA
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict) and raw.get("collected_at"):
            return raw["collected_at"]
        mtime = os.path.getmtime(path)
        return datetime.fromtimestamp(mtime).strftime("%Y.%m.%d %H:%M")
    except OSError:
        return ""


def recommend(user, policies=None, as_of=None, matcher=None, top_n=None,
              use_embeddings=True, verbose=False):
    """
    전체 파이프라인 실행.
    반환: list[dict] — policy에 fit(적합도%), score_parts, matched, notes,
                       days_left, deadline_soon, reason, checklist 필드가 붙은 사본
    """
    if policies is None:
        policies, loaded_as_of = load_policies()
        as_of = as_of or loaded_as_of
    as_of = as_of or date.today()

    # 1) 규칙 필터
    passed = []
    for p in policies:
        ok, matched, notes = check_eligibility(p, user, as_of)
        if ok:
            passed.append((p, matched, notes))
    if not passed:
        return []

    # 2) 의미 매칭
    if matcher is None:
        matcher = InterestMatcher([p for p, _, _ in passed],
                                  use_embeddings=use_embeddings, verbose=verbose)
        interest_scores = matcher.score(user.interest_query())
    else:   # 전체 정책으로 만든 matcher 재사용(앱에서 캐싱) → 정책 id로 매핑
        all_scores = matcher.score(user.interest_query())
        idx = {p.get("id"): i for i, p in enumerate(matcher.policies)}
        # matcher가 모르는 신규 정책(데이터 갱신 직후)은 중립 점수로 폴백
        interest_scores = [all_scores[idx[pid]] if (pid := p.get("id")) in idx else 0.5
                           for p, _, _ in passed]

    # 3) 가중 스코어
    results = []
    for (p, matched, notes), i_score in zip(passed, interest_scores):
        benefit = float(p.get("benefit_score") or 0.3)
        # 대출(한도)·적금/청약(본인 납입 포함 만기액)은 직접 지원금이 아님
        # → 지원효과 점수 상한 (총액 합산 제외와 동일 논리)
        p_text = p.get("name", "") + " " + " ".join(p.get("keywords", []))
        if any(k in p_text for k in ("대출", "융자", "적금", "저축", "청약", "자산형성")):
            benefit = min(benefit, 0.45)
        parts = {
            "eligibility": _eligibility_score(matched, notes,
                                              special=bool(p.get("special_req"))),
            "interest":    i_score,
            "benefit":     benefit,
            "deadline":    _deadline_score(p, as_of),
            "feasibility": _feasibility_score(p, as_of),
        }
        total = sum(WEIGHTS[k] * v for k, v in parts.items())
        item = dict(p)
        # 스킴 없는 URL('www.…')은 상대경로로 렌더되므로 정규화
        u = str(item.get("url") or "").strip()
        if u and not u.startswith("http"):
            item["url"] = "https://" + u.lstrip("/")
        start_d = parse_date(p.get("apply_start"))
        item.update({
            "fit": round(total * 100),
            "score_parts": parts,
            "matched": matched,
            "notes": notes,
            "days_left": days_left(p, as_of),
            "deadline_soon": is_deadline_soon(p, as_of),
            "not_open_yet": bool(start_d and start_d > as_of),   # 아직 접수 시작 전
        })
        # 4) 설명 생성 (설명 전용 — 판정에 관여하지 않음)
        item["reason"] = generate_reason(item, user)
        item["checklist"] = generate_checklist(item, user)
        results.append(item)

    results.sort(key=lambda x: (-x["fit"], x["days_left"] if x["days_left"] is not None else 9999))
    return results[:top_n] if top_n else results


# ──────────────────────────────────────────────
# 4) 설명 생성 (추천 이유 / 한줄 요약 / 체크리스트)
#    ※ 자격 판정 결과를 받아 문장으로 풀어줄 뿐, 판정 자체는 규칙이 담당
# ──────────────────────────────────────────────
def generate_reason(item, user):
    lines = [f"✅ {m}" for m in item["matched"][:4]]
    parts = item["score_parts"]
    if parts["interest"] >= 0.6 and user.interest_query():
        lines.append(f"🎯 입력하신 관심분야와 의미적으로 높게 일치합니다 (일치도 {parts['interest'] * 100:.0f}%)")
    d = item["days_left"]
    if item["deadline_soon"]:
        lines.append(f"⏰ 마감까지 {d}일 — 서둘러 신청하는 것이 좋아요")
    elif d is None:
        lines.append("🔁 상시 접수 정책이라 준비되는 대로 신청할 수 있어요")
    if item.get("amount_max"):
        lines.append(f"💰 {item.get('amount_label', '')} 규모의 지원 효과가 기대됩니다")
    return lines


def generate_checklist(item, user):
    checks = []
    if item.get("special_req"):
        checks.append(f"⚠️ 특정 자격 요건이 있는 정책이에요: "
                      f"\"{str(item['special_req'])[:60]}…\" — 본인 해당 여부를 먼저 확인하세요")
    checks += [f"⚠️ {n}" for n in item["notes"]]
    kw = " ".join(item.get("keywords", [])) + item.get("name", "") + item.get("summary", "")
    if "무주택" in str(item.get("eligibility", {}).get("housing", [])):
        checks.append("무주택 여부 증빙(건축물대장·등기부등본 등) 준비")
    if any(k in kw for k in ("대출", "융자")):
        checks.append("대출 상품이므로 상환 계획·금리 조건을 먼저 확인")
    if any(k in kw for k in ("저축", "자산형성", "통장")):
        checks.append("매월 저축 유지 가능 여부 확인 (중도해지 시 지원금 회수 가능)")
    if item.get("days_left") is not None:
        checks.append(f"신청 마감일({item.get('apply_end')}) 전 서류 제출 완료")
    checks.append("공식 페이지에서 최신 공고문·세부 자격 재확인")
    return checks


def generate_one_liner(results, user):
    """대시보드 상단 'AI 한줄 요약'"""
    if not results:
        return f"{user.name}님 조건에 맞는 정책을 찾지 못했어요. 조건을 조금 넓혀 다시 분석해 보세요."
    n = len(results)
    top = results[0]
    soon = sum(1 for r in results if r["deadline_soon"])
    msg = f"{user.name}님은 지금 {n}개 정책의 지원 대상이에요! 특히 '{top['name']}'(적합도 {top['fit']}%)부터 확인해 보세요."
    if soon:
        msg += f" 이 중 {soon}개는 마감이 일주일 이내라 서두르는 게 좋아요."
    return msg


def is_direct_benefit(policy):
    """'직접 받는 지원금'인지 판정 — 대출 한도·자산형성 만기액·사업 예산(1,500만 초과) 제외.
    총 지원 규모 합산과 TOP 3 혜택 선정이 같은 기준을 공유한다."""
    amt = policy.get("amount_max")
    if not amt or amt > EXCLUDE_FROM_TOTAL_CAP:
        return False
    text = (policy.get("name", "") + " " + " ".join(policy.get("keywords", []))
            + " " + str(policy.get("amount_label", "")))
    return not any(k in text for k in EXCLUDE_FROM_TOTAL_KEYWORDS)


def estimate_total_support(results):
    """추정 총 지원 규모 — 직접 지원금만 합산 (대출·자산형성·창업자금·1,500만원 초과 제외)"""
    direct = [r["amount_max"] for r in results if is_direct_benefit(r)]
    return sum(direct), len(direct)


def format_amount(won):
    if won >= 100000000:
        v = won / 100000000
        return f"{v:.1f}억원".replace(".0억", "억")
    if won >= 10000:
        man = won // 10000
        return f"{man:,}만원"
    return f"{won:,}원"


# ──────────────────────────────────────────────
# 단독 실행 데모
# ──────────────────────────────────────────────
if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    policies, as_of = load_policies()
    user = UserProfile(
        name="임주형", age=25, region="서울", status="대학생",
        school="광운대학교", housing="무주택", income_pct=100,
        interests=["주거·독립", "학비·장학금"], interest_text="자취 월세 부담이 크고 등록금 지원이 필요해요",
    )

    print("=" * 62)
    print("「눈 떠보니 지원 대상이었습니다」 추천 엔진 데모")
    print(f"  기준일: {as_of} / 전체 정책: {len(policies)}건")
    print(f"  사용자: {user.name} (만 {user.age}세, {user.region}, {user.status}, "
          f"{user.housing}, 중위소득 {user.income_pct}%)")
    print(f"  관심분야: {user.interest_query()}")
    print("=" * 62)

    results = recommend(user, policies, as_of, verbose=True)
    total, counted = estimate_total_support(results)
    print(f"\n▶ 자격 충족 정책 {len(results)}건 / "
          f"추정 총 지원 규모 약 {format_amount(total)} (금액 산정 가능한 {counted}건 기준 추정치)\n")

    for rank, r in enumerate(results[:5], 1):
        d = r["days_left"]
        dl = "상시" if d is None else f"D-{d}"
        print(f"[{rank}] {r['name']}  — 적합도 {r['fit']}%  ({r['category']}, {r['org']}, {dl})")
        print(f"    {r.get('amount_label', '')}")
        for line in r["reason"][:3]:
            print(f"    {line}")
        print()

    print("💬 AI 한줄 요약:", generate_one_liner(results, user))
    print("\n※ 본 결과는 사전 자가진단용 추정이며, 최종 자격은 각 기관의 공식 심사 기준을 따릅니다.")
