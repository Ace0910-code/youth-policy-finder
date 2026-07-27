# -*- coding: utf-8 -*-
"""사전계산 임베딩 팩 생성 — 배포 서버(모델 미설치)에서도 로컬과 동일한 의미 매칭

정책 전건 임베딩 + 관심분야 태그 조합(2^8-1=255종) 질의 임베딩을 data/emb_pack.npz로
저장한다. 데이터 갱신(demo_realdata.py --collect) 후 자동 호출되며, 단독 실행도 가능:

    python build_emb_pack.py
"""
import os
import sys
from itertools import combinations

from recommender import (DATA_DIR, INTEREST_CATALOG, InterestMatcher,
                         load_policies)

PACK_PATH = os.path.join(DATA_DIR, "emb_pack.npz")


def build(verbose=True):
    import numpy as np

    policies, _ = load_policies()
    matcher = InterestMatcher(policies, use_embeddings=True, verbose=verbose)
    if matcher.mode != "embedding":
        raise RuntimeError("임베딩 모델을 로드할 수 없어 팩을 만들 수 없습니다 "
                           "(requirements-full.txt 환경에서 실행하세요)")

    # 관심 태그의 모든 조합 (카탈로그 순서 유지 → interest_query 정규화와 일치)
    queries = [" ".join(combo)
               for r in range(1, len(INTEREST_CATALOG) + 1)
               for combo in combinations(INTEREST_CATALOG, r)]
    if verbose:
        print(f"[pack] 질의 {len(queries)}종 임베딩 생성 중...")
    q_emb = matcher._model.encode([matcher._prefix(q, "q") for q in queries],
                                  normalize_embeddings=True, show_progress_bar=False)

    np.savez_compressed(
        PACK_PATH,
        policy_key=matcher._policies_key(),
        policy_emb=np.asarray(matcher._emb, dtype="float32"),
        query_texts=np.array(queries),
        query_emb=np.asarray(q_emb, dtype="float32"),
    )
    size_mb = os.path.getsize(PACK_PATH) / 1e6
    if verbose:
        print(f"[pack] 저장: {PACK_PATH} ({size_mb:.1f}MB, "
              f"정책 {len(policies)}건 × 질의 {len(queries)}종)")
    return PACK_PATH


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    build()
