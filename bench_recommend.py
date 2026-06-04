"""
추천 파이프라인 4단계 비교 벤치마크
=====================================
Stage 1: Vector only
Stage 2: Vector + Neo4j
Stage 3: Vector + Neo4j + Reranker
Stage 4: 파라미터 스윕 (VECTOR_CANDIDATES × RERANK_TOP_N 조합)


결과:
  bench_result.json   (전체 raw 데이터)
  bench_summary.txt   (터미널 출력 그대로)
"""

import asyncio
import json
import math
import os
import sys
import time
import uuid
import copy
import psycopg2
from datetime import date, datetime
from typing import Any
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# =============================================
# 공통 설정
# =============================================
K = 3  # Precision@K, Hit Rate@K, NDCG@K

GROUND_TRUTH_USERS = [
    {
        "user_id": "01BENCH00000000000001",
        "name": "식비_교통_중심",
        "profile": {"birth": date(1998, 1, 15), "sex": "남자", "monthly_income": 3500000},
        "monthly_summary": [
            {"category": "식비",  "amount": 200000, "ratio": 45.0},
            {"category": "교통",  "amount": 120000, "ratio": 27.0},
            {"category": "카페",  "amount": 60000,  "ratio": 13.5},
            {"category": "쇼핑",  "amount": 40000,  "ratio": 9.0},
            {"category": "기타",  "amount": 24000,  "ratio": 5.5},
        ],
        "ground_truth": {
            "cards":      ["Deep Dream 카드", "1Q 청년 카드", "청춘대로 TOK TOK"],
            "insurances": ["애니핏 플러스", "운전자보험 플러스"],
            "policies":   ["청년 교통비 지원", "청년희망적금", "국민내일배움카드"],
        },
    },
    {
        "user_id": "01BENCH00000000000002",
        "name": "쇼핑_카페_중심",
        "profile": {"birth": date(2000, 5, 20), "sex": "여자", "monthly_income": 2800000},
        "monthly_summary": [
            {"category": "쇼핑",  "amount": 180000, "ratio": 42.0},
            {"category": "카페",  "amount": 100000, "ratio": 23.0},
            {"category": "식비",  "amount": 80000,  "ratio": 19.0},
            {"category": "문화",  "amount": 40000,  "ratio": 9.0},
            {"category": "기타",  "amount": 30000,  "ratio": 7.0},
        ],
        "ground_truth": {
            "cards":      ["올바른FLEX 카드", "Deep Dream 카드", "청춘대로 TOK TOK"],
            "insurances": ["애니핏 플러스", "암보험 다이렉트"],
            "policies":   ["청년 월세 지원", "청년희망적금", "서울 청년수당"],
        },
    },
    {
        "user_id": "01BENCH00000000000003",
        "name": "저소득_주거_중심",
        "profile": {"birth": date(1996, 8, 10), "sex": "남자", "monthly_income": 2200000},
        "monthly_summary": [
            {"category": "주거",  "amount": 400000, "ratio": 50.0},
            {"category": "식비",  "amount": 150000, "ratio": 18.8},
            {"category": "교통",  "amount": 80000,  "ratio": 10.0},
            {"category": "통신",  "amount": 80000,  "ratio": 10.0},
            {"category": "기타",  "amount": 90000,  "ratio": 11.2},
        ],
        "ground_truth": {
            "cards":      ["Mr.Life 카드", "Deep Dream 카드", "1Q 청년 카드"],
            "insurances": ["실손의료보험 4세대", "운전자보험 플러스"],
            "policies":   ["청년 월세 지원", "청년 전세 대출 버팀목", "청년 전세 대출"],
        },
    },
]
# Stage 4 파라미터 스윕 조합
PARAM_SWEEP = [
    {"vector_candidates": 20, "rerank_top_n": 5},
    {"vector_candidates": 30, "rerank_top_n": 7},
    {"vector_candidates": 50, "rerank_top_n": 10},
    {"vector_candidates": 50, "rerank_top_n": 15},
    {"vector_candidates": 30, "rerank_top_n": 999},  # 자르지 않고 재정렬만
]

# =============================================
# DB 유틸
# =============================================
def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode=os.getenv("DB_SSLMODE", "require"),
    )


def setup_users():
    print("[Setup] 테스트 유저 DB 세팅...")
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now()
    for user in GROUND_TRUTH_USERS:
        cur.execute("""
            INSERT INTO user_profile (user_id, birth, sex, monthly_income)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                birth=EXCLUDED.birth, sex=EXCLUDED.sex, monthly_income=EXCLUDED.monthly_income
        """, (user["user_id"], user["profile"]["birth"], user["profile"]["sex"], user["profile"]["monthly_income"]))
        cur.execute("DELETE FROM monthly_summary WHERE user_id=%s", (user["user_id"],))
        for s in user["monthly_summary"]:
            cur.execute("""
                INSERT INTO monthly_summary (summary_id, user_id, year, month, category, amount, ratio, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (str(uuid.uuid4()).replace("-","")[:26], user["user_id"],
                  now.year, now.month, s["category"], s["amount"], s["ratio"], now))
        conn.commit()
        print(f"  ✓ {user['name']} ({user['user_id']})")
    cur.close(); conn.close()


def fetch_results(user_id: str) -> dict:
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT cp.card_name FROM recommend_card rc
        JOIN card_product cp ON rc.card_product_id = cp.key
        WHERE rc.user_id=%s ORDER BY rc.created_at DESC
    """, (user_id,))
    cards = [r[0] for r in cur.fetchall()]
    cur.execute("""
        SELECT ip.insurance_name FROM recommend_insurance ri
        JOIN insurance_product ip ON ri.insurance_product_id = ip.key
        WHERE ri.user_id=%s ORDER BY ri.created_at DESC
    """, (user_id,))
    insurances = [r[0] for r in cur.fetchall()]
    cur.execute("""
        SELECT pp.policy_name FROM recommend_policy rp
        JOIN policy_product pp ON rp.policy_product_id = pp.key
        WHERE rp.user_id=%s ORDER BY rp.created_at DESC
    """, (user_id,))
    policies = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()
    return {"cards": cards, "insurances": insurances, "policies": policies}


# =============================================
# 평가 지표
# =============================================
def hit_rate(rec, gt, k):
    return sum(1 for x in rec[:k] if x in gt) / len(gt) if gt else 0.0

def precision_at_k(rec, gt, k):
    return sum(1 for x in rec[:k] if x in gt) / k if k > 0 else 0.0

def ndcg_at_k(rec, gt, k):
    dcg  = sum(1.0/math.log2(i+2) for i,x in enumerate(rec[:k]) if x in gt)
    idcg = sum(1.0/math.log2(i+2) for i in range(min(len(gt), k)))
    return dcg/idcg if idcg > 0 else 0.0

def mrr(rec, gt):
    for i, x in enumerate(rec):
        if x in gt: return 1.0/(i+1)
    return 0.0

def evaluate(user, recommended):
    scores = {}
    for ptype in ["cards", "insurances", "policies"]:
        rec = recommended.get(ptype, [])
        gt  = user["ground_truth"][ptype]
        scores[ptype] = {
            f"hit_rate@{K}":  round(hit_rate(rec, gt, K), 4),
            f"precision@{K}": round(precision_at_k(rec, gt, K), 4),
            f"ndcg@{K}":      round(ndcg_at_k(rec, gt, K), 4),
            "mrr":            round(mrr(rec, gt), 4),
            "recommended":    rec,
            "ground_truth":   gt,
            "hits":           [x for x in rec if x in gt],
        }
    avg = lambda key: sum(scores[p][key] for p in ["cards","insurances","policies"]) / 3
    scores["overall"] = {
        f"avg_hit_rate@{K}":  round(avg(f"hit_rate@{K}"),  4),
        f"avg_precision@{K}": round(avg(f"precision@{K}"), 4),
        f"avg_ndcg@{K}":      round(avg(f"ndcg@{K}"),      4),
        "avg_mrr":            round(avg("mrr"),             4),
    }
    return scores


# =============================================
# Mock 클라이언트 (Neo4j / Reranker ON/OFF 제어)
# =============================================
class DisabledNeo4jClient:
    """Neo4j OFF 모드 - 빈 결과 반환."""
    def fetch_candidates_by_categories(self, *a, **kw): return {"cards":[], "insurances":[], "policies":[]}
    def fetch_candidates_by_cf(self, *a, **kw): return {"cards":[], "insurances":[], "policies":[]}
    def fetch_triples(self, *a, **kw): return []


class DisabledRerankerClient:
    """Reranker OFF 모드 - 원본 순서 그대로."""
    def rerank(self, query, documents, top_n=7):
        return list(range(min(top_n, len(documents))))


# =============================================
# 파이프라인 실행 (모드별 monkey-patch 적용)
# =============================================
async def run_pipeline_with_config(
    user_id: str,
    use_neo4j: bool = True,
    use_reranker: bool = True,
    vector_candidates: int = 30,
    rerank_top_n: int = 7,
) -> dict:
    """
    nodes 모듈의 전역 변수와 외부 클라이언트를 패치해서
    코드 수정 없이 4가지 모드 실행.
    """
    import app.domain.recommend_ai.nodes as nodes_mod
    import app.core.client.neo4j_client as neo4j_mod
    import app.domain.recommend_ai.reranker as reranker_mod

    # --- 파라미터 패치 ---
    orig_vec = nodes_mod.VECTOR_CANDIDATES
    orig_top = nodes_mod.RERANK_TOP_N
    nodes_mod.VECTOR_CANDIDATES = vector_candidates
    nodes_mod.RERANK_TOP_N = rerank_top_n

    # --- Neo4j 패치 ---
    orig_neo4j = neo4j_mod.neo4j_client
    if not use_neo4j:
        neo4j_mod.neo4j_client = DisabledNeo4jClient()
        # nodes.py 내부에서 직접 import한 경우도 커버
        nodes_mod.neo4j_client = neo4j_mod.neo4j_client  # type: ignore

    # --- Reranker 패치 ---
    orig_reranker = reranker_mod.reranker_client
    if not use_reranker:
        reranker_mod.reranker_client = DisabledRerankerClient()

    # --- LangGraph 캐시 무효화 (파라미터 바뀌면 그래프 재빌드 필요) ---
    import app.domain.recommend_ai.graph as graph_mod
    graph_mod._recommend_graph = None

    timing: dict[str, float] = {}
    candidate_counts: dict[str, Any] = {}
    t0 = time.perf_counter()

    try:
        from app.domain.recommend_ai.graph import run_recommend_pipeline
        result = await run_recommend_pipeline(user_id)
    finally:
        # 복원
        nodes_mod.VECTOR_CANDIDATES = orig_vec
        nodes_mod.RERANK_TOP_N = orig_top
        neo4j_mod.neo4j_client = orig_neo4j
        if hasattr(nodes_mod, "neo4j_client"):
            nodes_mod.neo4j_client = orig_neo4j  # type: ignore
        reranker_mod.reranker_client = orig_reranker
        graph_mod._recommend_graph = None  # 복원 후 재빌드되도록

    t1 = time.perf_counter()
    total_ms = round((t1 - t0) * 1000, 1)

    candidate_counts = {
        "cards":      len(result.get("card_candidates", [])),
        "insurances": len(result.get("insurance_candidates", [])),
        "policies":   len(result.get("policy_candidates", [])),
        "filtered_policies": len(result.get("filtered_policies", [])),
    }

    return {
        "result":           result,
        "total_ms":         total_ms,
        "candidate_counts": candidate_counts,
        "error":            result.get("error"),
    }


# =============================================
# 단일 스테이지 평가
# =============================================
async def run_stage(
    stage_name: str,
    use_neo4j: bool,
    use_reranker: bool,
    vector_candidates: int = 30,
    rerank_top_n: int = 7,
) -> dict:
    print(f"\n{'='*60}")
    print(f"  {stage_name}")
    print(f"  Neo4j={use_neo4j} | Reranker={use_reranker} | "
          f"vec_cand={vector_candidates} | rerank_top={rerank_top_n}")
    print(f"{'='*60}")

    per_user = []
    all_overall = []
    latencies = []

    for user in GROUND_TRUTH_USERS:
        uid = user["user_id"]
        print(f"\n  ▶ {user['name']} ({uid})")

        try:
            run = await run_pipeline_with_config(
                uid,
                use_neo4j=use_neo4j,
                use_reranker=use_reranker,
                vector_candidates=vector_candidates,
                rerank_top_n=rerank_top_n,
            )
        except Exception as e:
            print(f"    ❌ 파이프라인 예외: {e}")
            continue

        if run["error"]:
            print(f"    ❌ 파이프라인 에러: {run['error']}")
            continue

        latencies.append(run["total_ms"])
        cands = run["candidate_counts"]
        print(f"    후보: 카드 {cands['cards']}개 | 보험 {cands['insurances']}개 "
              f"| 정책 {cands['policies']}개 → 필터 후 {cands['filtered_policies']}개")
        print(f"    ⏱  {run['total_ms']:.0f}ms")

        recommended = fetch_results(uid)
        print(f"    최종추천: 카드 {len(recommended['cards'])}개 "
              f"| 보험 {len(recommended['insurances'])}개 "
              f"| 정책 {len(recommended['policies'])}개")

        scores = evaluate(user, recommended)
        ov = scores["overall"]
        print(f"    Hit@{K}={ov[f'avg_hit_rate@{K}']:.4f} | "
              f"Prec@{K}={ov[f'avg_precision@{K}']:.4f} | "
              f"NDCG@{K}={ov[f'avg_ndcg@{K}']:.4f} | "
              f"MRR={ov['avg_mrr']:.4f}")

        # 카테고리별 상세
        for label, key in [("카드","cards"),("보험","insurances"),("정책","policies")]:
            s = scores[key]
            hits_str = str(s["hits"]) if s["hits"] else "없음"
            print(f"      {label}: 추천={s['recommended'][:3]} | 적중={hits_str}")

        per_user.append({
            "user_id": uid,
            "user_name": user["name"],
            "latency_ms": run["total_ms"],
            "candidate_counts": cands,
            "scores": scores,
            "recommended": recommended,
        })
        all_overall.append(ov)

    if not all_overall:
        print("  ❌ 유효한 결과 없음")
        return {"stage": stage_name, "error": "no results"}

    # 전체 평균
    def avg_metric(key):
        return round(sum(o[key] for o in all_overall) / len(all_overall), 4)

    overall = {
        f"avg_hit_rate@{K}":  avg_metric(f"avg_hit_rate@{K}"),
        f"avg_precision@{K}": avg_metric(f"avg_precision@{K}"),
        f"avg_ndcg@{K}":      avg_metric(f"avg_ndcg@{K}"),
        "avg_mrr":            avg_metric("avg_mrr"),
        "avg_latency_ms":     round(sum(latencies)/len(latencies), 1),
        "min_latency_ms":     round(min(latencies), 1),
        "max_latency_ms":     round(max(latencies), 1),
    }

    print(f"\n  ── {stage_name} 전체 평균 ──")
    print(f"  Hit@{K}={overall[f'avg_hit_rate@{K}']:.4f} | "
          f"Prec@{K}={overall[f'avg_precision@{K}']:.4f} | "
          f"NDCG@{K}={overall[f'avg_ndcg@{K}']:.4f} | "
          f"MRR={overall['avg_mrr']:.4f}")
    print(f"  Latency: avg={overall['avg_latency_ms']}ms | "
          f"min={overall['min_latency_ms']}ms | max={overall['max_latency_ms']}ms")

    return {
        "stage": stage_name,
        "config": {
            "use_neo4j": use_neo4j,
            "use_reranker": use_reranker,
            "vector_candidates": vector_candidates,
            "rerank_top_n": rerank_top_n,
        },
        "per_user": per_user,
        "overall": overall,
    }


# =============================================
# 비교 테이블 출력
# =============================================
def print_comparison_table(stages: list[dict]):
    print("\n\n" + "="*90)
    print("📊 전체 비교 테이블")
    print("="*90)

    header = f"  {'스테이지':<28} {'Hit@3':>7} {'Prec@3':>7} {'NDCG@3':>7} {'MRR':>7} {'Latency(ms)':>12}"
    print(header)
    print(f"  {'-'*80}")

    baseline = None
    for stage in stages:
        if "error" in stage:
            continue
        ov = stage["overall"]
        name = stage["stage"]
        lat = f"{ov['avg_latency_ms']:.0f}"

        hit  = ov[f"avg_hit_rate@{K}"]
        prec = ov[f"avg_precision@{K}"]
        ndcg = ov[f"avg_ndcg@{K}"]
        mmr  = ov["avg_mrr"]

        if baseline is None:
            baseline = ov
            suffix = "  ← baseline"
        else:
            def delta(new, old):
                d = new - old
                return f"({'+' if d>=0 else ''}{d:.4f})"
            suffix = (f"  Hit{delta(hit,baseline[f'avg_hit_rate@{K}'])} "
                      f"Prec{delta(prec,baseline[f'avg_precision@{K}'])} "
                      f"NDCG{delta(ndcg,baseline[f'avg_ndcg@{K}'])}")

        print(f"  {name:<28} {hit:>7.4f} {prec:>7.4f} {ndcg:>7.4f} {mmr:>7.4f} {lat:>10}ms{suffix}")

    print("="*90)

    # 파라미터 스윕 비교
    sweep_stages = [s for s in stages if "sweep" in s.get("stage","").lower() or "param" in s.get("stage","").lower()]
    if sweep_stages:
        print("\n📐 Stage 4 파라미터 스윕 상세")
        print(f"  {'vec_cand':>10} {'rerank_top':>10} {'Hit@3':>7} {'Prec@3':>7} {'NDCG@3':>7} {'MRR':>7} {'Latency':>10}")
        print(f"  {'-'*65}")
        for s in sweep_stages:
            cfg = s["config"]
            ov  = s["overall"]
            print(f"  {cfg['vector_candidates']:>10} {cfg['rerank_top_n']:>10} "
                  f"{ov[f'avg_hit_rate@{K}']:>7.4f} {ov[f'avg_precision@{K}']:>7.4f} "
                  f"{ov[f'avg_ndcg@{K}']:>7.4f} {ov['avg_mrr']:>7.4f} "
                  f"{ov['avg_latency_ms']:>9.0f}ms")


# =============================================
# 메인
# =============================================
async def main():
    print("🚀 추천 파이프라인 4단계 비교 벤치마크")
    print(f"   K={K} | 유저={len(GROUND_TRUTH_USERS)}명 | 시작={datetime.now():%Y-%m-%d %H:%M:%S}")

    setup_users()

    all_stages = []

    # ── Stage 1: Vector only ──
    s1 = await run_stage(
        "Stage1: Vector Only",
        use_neo4j=False, use_reranker=False,
    )
    all_stages.append(s1)

    # ── Stage 2: Vector + Neo4j ──
    s2 = await run_stage(
        "Stage2: Vector + Neo4j",
        use_neo4j=True, use_reranker=False,
    )
    all_stages.append(s2)

    # ── Stage 3: Vector + Neo4j + Reranker ──
    s3 = await run_stage(
        "Stage3: + Reranker",
        use_neo4j=True, use_reranker=True,
        vector_candidates=30, rerank_top_n=7,
    )
    all_stages.append(s3)

    # ── Stage 4: 파라미터 스윕 ──
    print(f"\n\n{'='*60}")
    print(f"  Stage 4: 파라미터 스윕 ({len(PARAM_SWEEP)}개 조합)")
    print(f"{'='*60}")
    for i, params in enumerate(PARAM_SWEEP, 1):
        s4 = await run_stage(
            f"Stage4-{i}: vec={params['vector_candidates']} rerank={params['rerank_top_n']}",
            use_neo4j=True, use_reranker=True,
            vector_candidates=params["vector_candidates"],
            rerank_top_n=params["rerank_top_n"],
        )
        all_stages.append(s4)

    # 비교 출력
    print_comparison_table(all_stages)

    # 저장
    output = {
        "timestamp": datetime.now().isoformat(),
        "k": K,
        "users": len(GROUND_TRUTH_USERS),
        "stages": all_stages,
    }
    with open("bench_result.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n✅ 결과 저장: bench_result.json")
    print(f"   종료: {datetime.now():%Y-%m-%d %H:%M:%S}")


if __name__ == "__main__":
    asyncio.run(main())