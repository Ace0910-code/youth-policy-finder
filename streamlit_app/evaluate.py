# -*- coding: utf-8 -*-
"""
추천 정확도 검증: 가상 페르소나 24명 × Precision@5 / Recall@5 / Hit@5

정답 라벨 기준 (시스템 랭킹과 독립):
  ① 실제 자격 충족 (eligibility 필드를 직접 대조하는 독립 라벨러)
  ② 마감이 지나지 않음
  ③ 페르소나 관심분야에 해당 (정책 카테고리·키워드 → 관심 도메인 매핑)

단계 분리 분석:
  - 규칙 필터 미탐: 정답인데 자격 필터 단계에서 탈락한 정책 (목표 0건)
  - 랭킹 오탐   : 자격은 충족하지만 관심분야가 아닌데 Top5에 오른 정책

실행: python evaluate.py [--no-embed]
결과: evaluation/정확도_리포트.md
"""
import argparse
import os
import sys
from datetime import date

from recommender import (UserProfile, load_policies, recommend, parse_date,
                         InterestMatcher, STATUS_SYNONYMS, WEIGHTS,
                         check_eligibility, DEFAULT_DATA, REAL_DATA)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_PATH = os.path.join(BASE_DIR, "evaluation", "정확도_리포트.md")

# ──────────────────────────────────────────────
# 독립 라벨러 (recommender.check_eligibility를 호출하지 않고 필드를 직접 대조)
# ──────────────────────────────────────────────
DOMAIN_TAGS = ["주거·독립", "취업·이직", "창업", "학비·장학금",
               "자기계발·교육", "생활비·교통", "문화·여가", "자산형성"]


def policy_domains(p):
    """정책 → 관심 도메인 집합 (정답 라벨용, 랭킹 로직과 무관한 사전 정의 매핑).
    분류 체계(category)가 거친 실데이터를 위해 정책명·키워드의 명시적 단서도 반영한다
    (예: 생활·교통으로 분류된 '○○ 취업지원사업'은 취업 도메인으로도 인정)."""
    cat = p.get("category", "")
    kw = (" ".join(p.get("keywords", [])) + " " + p.get("name", "")
          + " " + (p.get("summary") or ""))
    domains = set()
    if cat == "주거":
        domains.add("주거·독립")
    elif cat == "취업·창업":
        if any(k in kw for k in ("창업", "스타트업", "사업화")):
            domains.add("창업")
        else:
            domains.add("취업·이직")
        if any(k in kw for k in ("자격", "응시료", "교육", "훈련", "어학")):
            domains.add("자기계발·교육")
    elif cat == "교육·장학":
        domains.add("학비·장학금")
        if any(k in kw for k in ("주거", "거주", "기숙사", "주거비")):
            domains.add("주거·독립")
    elif cat == "교육·역량":
        domains.add("자기계발·교육")
        if any(k in kw for k in ("장학", "학자금", "등록금", "수업료")):
            domains.add("학비·장학금")
    else:  # 생활·교통
        if any(k in kw for k in ("주거비", "월세", "임차")):
            domains.add("주거·독립")
        if any(k in kw for k in ("자산형성", "저축", "통장", "적금")):
            domains.add("자산형성")
        elif any(k in kw for k in ("문화", "공연", "전시", "예술")):
            domains.add("문화·여가")
        elif any(k in kw for k in ("취업", "일자리", "구직", "면접")):
            domains.add("취업·이직")
        elif any(k in kw for k in ("교육", "훈련", "자격")):
            domains.add("자기계발·교육")
        else:
            domains.add("생활비·교통")
    return domains


def label_eligible(p, persona, as_of):
    """자격 충족 + 마감 유효 여부를 정책 필드에서 직접 판정 (정답 라벨 ①②)"""
    e = p.get("eligibility", {}) or {}
    end = parse_date(p.get("apply_end"))
    if end is not None and end < as_of:
        return False
    a_min = e.get("age_min") or 0
    a_max = e.get("age_max") or 0
    if a_max in (0, None):
        a_min, a_max = a_min or 0, 200
    if not (a_min <= persona.age <= a_max):
        return False
    regions = e.get("regions") or ["전국"]
    if "전국" not in regions and persona.region not in regions:
        return False
    req = e.get("status") or []
    if req and not (STATUS_SYNONYMS.get(persona.status, {persona.status}) & set(req)):
        return False
    hous = e.get("housing") or []
    if hous and persona.housing not in hous:
        return False
    cap = e.get("income_max_pct")
    if cap is not None and persona.income_pct is not None and persona.income_pct > cap:
        return False
    return True


def label_relevant(p, persona, as_of):
    """정답 = 자격 충족 + 마감 유효 + 관심분야 일치 (①②③).
    특정자격 전용 정책(종교재단·자립준비청년 등)은 일반 청년 페르소나의 정답에서 제외
    — 해당 집단이 아니면 실제로 신청할 수 없는 정책이므로."""
    if p.get("special_req"):
        return False
    return (label_eligible(p, persona, as_of)
            and bool(policy_domains(p) & set(persona.interests)))


# ──────────────────────────────────────────────
# 가상 페르소나 24명 (서울/경기/인천, 연령·소득 경계 포함)
# ──────────────────────────────────────────────
def build_personas():
    P = UserProfile
    return [
        # 대학생 (8)
        P(name="김서준", age=20, region="서울", status="대학생", housing="무주택", income_pct=80,
          interests=["학비·장학금", "주거·독립"]),
        P(name="이서연", age=25, region="서울", status="대학생", housing="무주택", income_pct=100,
          interests=["주거·독립", "학비·장학금", "생활비·교통"]),
        P(name="박민준", age=19, region="서울", status="대학생", housing="무주택", income_pct=50,
          interests=["학비·장학금", "문화·여가", "생활비·교통"]),      # 19세 하한 경계
        P(name="최지우", age=24, region="경기", status="대학생", housing="무주택", income_pct=120,
          interests=["학비·장학금", "생활비·교통", "자기계발·교육"]),  # 경기 기본소득 24세 정확 대상
        P(name="정예은", age=23, region="경기", status="대학생", housing="무주택", income_pct=60,
          interests=["학비·장학금", "취업·이직"]),                     # 소득 60% 경계
        P(name="한지호", age=22, region="인천", status="대학생", housing="무주택", income_pct=90,
          interests=["학비·장학금", "주거·독립"]),
        P(name="서다은", age=26, region="서울", status="대학원생", housing="무주택", income_pct=110,
          interests=["주거·독립", "자기계발·교육"]),
        P(name="문준혁", age=21, region="경기", status="대학생", housing="자가", income_pct=None,
          interests=["학비·장학금", "자기계발·교육"]),                 # 소득 미상 + 유주택
        # 취업준비생 (6)
        P(name="오하린", age=27, region="서울", status="취업준비생", housing="무주택", income_pct=50,
          interests=["취업·이직", "주거·독립", "생활비·교통"]),
        P(name="배시우", age=34, region="서울", status="취업준비생", housing="무주택", income_pct=60,
          interests=["취업·이직", "자기계발·교육"]),                   # 34세 상한 경계
        P(name="신유나", age=25, region="경기", status="취업준비생", housing="무주택", income_pct=55,
          interests=["취업·이직", "자기계발·교육", "생활비·교통"]),
        P(name="장태양", age=28, region="인천", status="취업준비생", housing="무주택", income_pct=70,
          interests=["취업·이직", "주거·독립"]),
        P(name="윤채원", age=24, region="경기", status="취업준비생", housing="무주택", income_pct=None,
          interests=["취업·이직", "생활비·교통", "자기계발·교육"]),    # 소득 미상
        P(name="송지안", age=30, region="서울", status="취업준비생", housing="무주택", income_pct=151,
          interests=["취업·이직", "주거·독립"]),                       # 소득 150% 초과 경계
        # 사회초년생·재직자 (6)
        P(name="홍승우", age=28, region="인천", status="사회초년생", housing="무주택", income_pct=140,
          interests=["자산형성", "주거·독립"]),                        # 인천 통장(150%) 경계 내
        P(name="김나윤", age=31, region="서울", status="재직자", housing="무주택", income_pct=120,
          interests=["주거·독립", "자산형성"]),
        P(name="이도윤", age=35, region="서울", status="재직자", housing="무주택", income_pct=100,
          interests=["주거·독립", "자산형성", "자기계발·교육"]),       # 35세 → 19~34 정책 탈락 확인
        P(name="박소율", age=26, region="경기", status="사회초년생", housing="무주택", income_pct=90,
          interests=["자산형성", "생활비·교통", "주거·독립"]),
        P(name="정건우", age=33, region="인천", status="재직자", housing="무주택", income_pct=170,
          interests=["자산형성", "주거·독립"]),                        # 도약계좌(180%) 경계 내
        P(name="최아린", age=29, region="서울", status="프리랜서", housing="무주택", income_pct=110,
          interests=["자산형성", "문화·여가", "생활비·교통"]),
        # 무직·기타 (4)
        P(name="강예준", age=23, region="경기", status="무직", housing="무주택", income_pct=40,
          interests=["취업·이직", "생활비·교통"]),
        P(name="조수아", age=32, region="인천", status="무직", housing="무주택", income_pct=45,
          interests=["취업·이직", "자기계발·교육", "주거·독립"]),
        P(name="임하율", age=39, region="서울", status="재직자", housing="무주택", income_pct=130,
          interests=["주거·독립", "생활비·교통"]),                     # 39세 상한 경계(서울 월세 19~39)
        P(name="황은채", age=40, region="경기", status="재직자", housing="자가", income_pct=200,
          interests=["자산형성", "생활비·교통"]),                      # 40세 → 대부분 탈락 확인
    ]


# ──────────────────────────────────────────────
# 평가 실행
# ──────────────────────────────────────────────
def evaluate(use_embeddings=True, k=5, data_path=None):
    policies, as_of = load_policies(data_path)
    personas = build_personas()
    matcher = InterestMatcher(policies, use_embeddings=use_embeddings, verbose=True)

    rows, agg = [], {"p5": [], "p5_adj": [], "r5": [], "r10": [], "hit": [],
                     "elig_acc": [], "filter_miss": 0, "rank_fp": 0}
    for persona in personas:
        relevant_ids = {p["id"] for p in policies if label_relevant(p, persona, as_of)}
        eligible_ids = {p["id"] for p in policies if label_eligible(p, persona, as_of)}

        results = recommend(persona, policies, as_of, matcher=matcher)
        top_ids = [r["id"] for r in results[:k]]
        top10_ids = [r["id"] for r in results[:10]]
        sys_eligible_ids = {r["id"] for r in results}

        hits = len(set(top_ids) & relevant_ids)
        hits10 = len(set(top10_ids) & relevant_ids)
        n_rel = len(relevant_ids)
        p5 = hits / k
        p5_adj = hits / min(k, n_rel) if n_rel else 1.0     # 달성 가능 최대치 기준
        r5 = hits / n_rel if n_rel else 1.0
        r10 = hits10 / min(10, n_rel) if n_rel else 1.0     # 달성 가능 최대치(Top10) 기준
        r10_strict = hits10 / n_rel if n_rel else 1.0
        hit = 1.0 if hits else (1.0 if not n_rel else 0.0)

        # 조건 판정 정확도: 전체 정책에 대해 시스템 자격판정 vs 독립 라벨러 일치율
        agree = sum(1 for p in policies
                    if check_eligibility(p, persona, as_of)[0]
                    == label_eligible(p, persona, as_of))
        elig_acc = agree / len(policies)

        filter_miss = relevant_ids - sys_eligible_ids        # 규칙 필터 미탐
        rank_fp = [i for i in top_ids if i not in relevant_ids]  # 랭킹 오탐

        agg["p5"].append(p5); agg["p5_adj"].append(p5_adj)
        agg["r5"].append(r5); agg["r10"].append(r10)
        agg.setdefault("r10_strict", []).append(r10_strict)
        agg["hit"].append(hit)
        agg["elig_acc"].append(elig_acc)
        agg["filter_miss"] += len(filter_miss)
        agg["rank_fp"] += len(rank_fp)

        rows.append({
            "persona": persona, "n_relevant": n_rel, "n_eligible": len(eligible_ids),
            "hits": hits, "p5": p5, "p5_adj": p5_adj, "r5": r5, "r10": r10,
            "hit": hit, "elig_acc": elig_acc,
            "filter_miss": sorted(filter_miss), "rank_fp": rank_fp, "top_ids": top_ids,
        })
    return rows, agg, as_of, len(policies), matcher.mode


def write_report(rows, agg, as_of, n_policies, mode, k=5, report_path=REPORT_PATH):
    n = len(rows)
    mean = lambda xs: sum(xs) / len(xs)
    lines = [
        "# 추천 정확도 검증 리포트",
        "",
        f"- 평가일 기준 정책 기준일: **{as_of}** / 정책 풀: **{n_policies}건** / "
        f"페르소나: **{n}명** / 관심분야 매칭 모드: **{mode}**",
        "- 정답 라벨(시스템 랭킹과 독립): ① 자격 충족(독립 라벨러로 필드 직접 대조) "
        "② 마감 유효 ③ 관심분야 일치",
        f"- (조정) 지표 = 적중 수 ÷ min(K, 정답 수) — 정답이 K개 미만인 페르소나는 "
        "달성 가능한 최대치를 분모로 사용. (엄격) 지표는 정의 그대로 계산.",
        "- 조건 판정 정확도 = 페르소나×정책 전체 조합에서 시스템 자격 판정과 "
        "독립 라벨러 판정이 일치한 비율.",
        "",
        "## 종합 결과 (제안서 목표 지표 기준)",
        "",
        "| 지표 | 값 | 목표(제안서) | 판정 |",
        "|---|---|---|---|",
        f"| Precision@{k} (조정) | **{mean(agg['p5_adj']):.3f}** | ≥ 0.80 | "
        f"{'✅ 달성' if mean(agg['p5_adj']) >= 0.80 else '❌ 미달'} |",
        f"| Precision@{k} (엄격) | {mean(agg['p5']):.3f} | - | - |",
        f"| Recall@10 (조정) | **{mean(agg['r10']):.3f}** | ≥ 0.70 | "
        f"{'✅ 달성' if mean(agg['r10']) >= 0.70 else '❌ 미달'} |",
        f"| Recall@10 (엄격) | {mean(agg['r10_strict']):.3f} | - | - |",
        f"| 조건 판정 정확도 | **{mean(agg['elig_acc']):.3f}** | ≥ 0.90 | "
        f"{'✅ 달성' if mean(agg['elig_acc']) >= 0.90 else '❌ 미달'} |",
        f"| Recall@{k} | {mean(agg['r5']):.3f} | - | - |",
        f"| Hit@{k} | {mean(agg['hit']):.3f} | - | - |",
        "",
        "## 단계 분리 분석",
        "",
        f"- **규칙 필터 미탐** (정답인데 자격 필터에서 탈락): **{agg['filter_miss']}건** "
        f"{'→ 규칙 필터가 정답을 놓치지 않음 ✅' if agg['filter_miss'] == 0 else '→ 필터 규칙 점검 필요 ⚠️'}",
        f"- **랭킹 오탐** (자격은 충족하나 관심분야 밖인데 Top{k} 진입): **{agg['rank_fp']}건** "
        f"(페르소나당 평균 {agg['rank_fp'] / n:.2f}건)",
        "  - 오탐은 전부 '자격을 충족하는' 정책이므로 안전성 문제가 아니라 관심도 정렬의 문제임",
        "",
        "## 페르소나별 상세",
        "",
        "| # | 이름 | 나이 | 지역 | 상태 | 소득% | 정답 | 자격충족 | 적중 | P@5(조정) | R@10(조정) | 판정정확 | Hit |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        p = r["persona"]
        inc = "미상" if p.income_pct is None else p.income_pct
        lines.append(
            f"| {i} | {p.name} | {p.age} | {p.region} | {p.status} | {inc} | "
            f"{r['n_relevant']} | {r['n_eligible']} | {r['hits']} | "
            f"{r['p5_adj']:.2f} | {r['r10']:.2f} | {r['elig_acc']:.3f} | "
            f"{'O' if r['hit'] else 'X'} |")
    lines += ["", "### 랭킹 오탐 상세 (관심분야 밖 Top5 진입)", ""]
    any_fp = False
    for r in rows:
        if r["rank_fp"]:
            any_fp = True
            lines.append(f"- {r['persona'].name}: {', '.join(r['rank_fp'])}")
    if not any_fp:
        lines.append("- 없음")
    lines += ["", "※ 동일 스크립트를 `--data sample`(직접 작성 30건) / "
              "`--data real`(4종 API 수집분)으로 실행해 두 데이터셋 모두 검증한다.", ""]

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="페르소나 정확도 검증")
    ap.add_argument("--no-embed", action="store_true", help="키워드 폴백 모드로 평가")
    ap.add_argument("--data", choices=["auto", "sample", "real"], default="auto",
                    help="평가 데이터: sample=직접 작성 30건, real=API 수집분, "
                         "auto=real 있으면 real")
    args = ap.parse_args()

    data_path = {"auto": None, "sample": DEFAULT_DATA, "real": REAL_DATA}[args.data]
    report_path = {"auto": REPORT_PATH,
                   "sample": REPORT_PATH.replace(".md", "_샘플.md"),
                   "real": REPORT_PATH.replace(".md", "_실데이터.md")}[args.data]
    if args.data == "real" and not os.path.exists(REAL_DATA):
        print("policies_real.json이 없습니다. demo_realdata.py를 먼저 실행하세요.")
        sys.exit(1)

    rows, agg, as_of, n_policies, mode = evaluate(use_embeddings=not args.no_embed,
                                                  data_path=data_path)
    path = write_report(rows, agg, as_of, n_policies, mode, report_path=report_path)

    mean = lambda xs: sum(xs) / len(xs)
    print("\n" + "=" * 56)
    print(f"페르소나 {len(rows)}명 평가 완료 (매칭 모드: {mode}, 정책 {n_policies}건, "
          f"기준일 {as_of})")
    print(f"  Precision@5(조정): {mean(agg['p5_adj']):.3f}  (목표 0.80 "
          f"{'달성 ✅' if mean(agg['p5_adj']) >= 0.80 else '미달 ❌'})")
    print(f"  Precision@5(엄격): {mean(agg['p5']):.3f}")
    print(f"  Recall@10(조정)  : {mean(agg['r10']):.3f}  (목표 0.70 "
          f"{'달성 ✅' if mean(agg['r10']) >= 0.70 else '미달 ❌'})")
    print(f"  조건 판정 정확도 : {mean(agg['elig_acc']):.3f}  (목표 0.90 "
          f"{'달성 ✅' if mean(agg['elig_acc']) >= 0.90 else '미달 ❌'})")
    print(f"  Recall@5: {mean(agg['r5']):.3f} / Hit@5: {mean(agg['hit']):.3f}")
    print(f"  규칙 필터 미탐   : {agg['filter_miss']}건 / 랭킹 오탐: {agg['rank_fp']}건")
    print(f"  리포트: {path}")


if __name__ == "__main__":
    main()
