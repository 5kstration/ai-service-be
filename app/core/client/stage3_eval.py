"""
3단계 평가 - Ground Truth 기반 정량 평가
LangGraph + 리랭커 (klue-cross-encoder-v1) 적용 후 동일 Ground Truth로 비교

실행: python app/core/client/stage3_eval.py (프로젝트 루트에서)
결과: stage3_eval_result.json
"""
import asyncio
import json
import math
import os
import sys
import uuid
import psycopg2
from datetime import date, datetime
from dotenv import load_dotenv

sys.path.insert(0, "/home/server2/ai-service-be")
load_dotenv()

from app.domain.recommend_ai.graph import run_recommend_pipeline

K = 3

# =============================================
# Ground Truth (1/2단계와 동일)
# =============================================
GROUND_TRUTH_USERS = [
    {
        "user_id":   "01HXGT000000000001",
        "name":      "식비_교통_중심",
        "profile": {
            "birth":          date(1998, 1, 15),
            "sex":            "남자",
            "monthly_income": 3500000,
        },
        "monthly_summary": [
            {"category": "식비",  "amount": 200000, "ratio": 45.0},
            {"category": "교통",  "amount": 120000, "ratio": 27.0},
            {"category": "카페",  "amount": 60000,  "ratio": 13.5},
            {"category": "쇼핑",  "amount": 40000,  "ratio": 9.0},
            {"category": "기타",  "amount": 24000,  "ratio": 5.5},
        ],
        "ground_truth": {
            "cards":      ["신한 Deep Dream 카드", "하나 1Q카드", "KB 청춘대로 TOK TOK카드"],
            "insurances": ["삼성화재 애니핏 플러스", "현대해상 운전자보험 플러스"],
            "policies":   ["청년 교통비 지원", "청년희망적금", "내일배움카드"],
        }
    },
    {
        "user_id":   "01HXGT000000000002",
        "name":      "쇼핑_카페_중심",
        "profile": {
            "birth":          date(2000, 5, 20),
            "sex":            "여자",
            "monthly_income": 2800000,
        },
        "monthly_summary": [
            {"category": "쇼핑",  "amount": 180000, "ratio": 42.0},
            {"category": "카페",  "amount": 100000, "ratio": 23.0},
            {"category": "식비",  "amount": 80000,  "ratio": 19.0},
            {"category": "문화",  "amount": 40000,  "ratio": 9.0},
            {"category": "기타",  "amount": 30000,  "ratio": 7.0},
        ],
        "ground_truth": {
            "cards":      ["NH올원 e카드", "신한 Deep Dream 카드", "KB 청춘대로 TOK TOK카드"],
            "insurances": ["삼성화재 애니핏 플러스", "KB 암보험 다이렉트"],
            "policies":   ["청년 월세 지원", "청년희망적금", "서울 청년 수당"],
        }
    },
    {
        "user_id":   "01HXGT000000000003",
        "name":      "저소득_주거_중심",
        "profile": {
            "birth":          date(1996, 8, 10),
            "sex":            "남자",
            "monthly_income": 2200000,
        },
        "monthly_summary": [
            {"category": "주거",  "amount": 400000, "ratio": 50.0},
            {"category": "식비",  "amount": 150000, "ratio": 18.8},
            {"category": "교통",  "amount": 80000,  "ratio": 10.0},
            {"category": "통신",  "amount": 80000,  "ratio": 10.0},
            {"category": "기타",  "amount": 90000,  "ratio": 11.2},
        ],
        "ground_truth": {
            "cards":      ["신한 Mr.Life 카드", "신한 Deep Dream 카드", "하나 1Q카드"],
            "insurances": ["라이프플러스 실손보험", "현대해상 운전자보험 플러스"],
            "policies":   ["청년 월세 지원", "청년 전세임대주택", "청년 주거급여 분리지급"],
        }
    },
]

# 이전 단계 기준선
BASELINES = {
    "stage1": {
        "hit_rate@3":  0.1481,
        "precision@3": 0.1481,
        "ndcg@3":      0.1440,
        "mrr":         0.2593,
    },
    "stage2": {
        "hit_rate@3":  0.2593,
        "precision@3": 0.2222,
        "ndcg@3":      0.3256,
        "mrr":         0.6111,
    },
}


# =============================================
# DB 연결
# =============================================
def get_main_db():
    return psycopg2.connect(
        host     = os.getenv("DB_HOST"),
        port     = os.getenv("DB_PORT", 5432),
        dbname   = os.getenv("DB_NAME"),
        user     = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        sslmode  = os.getenv("DB_SSLMODE", "require"),
    )


# =============================================
# 테스트 유저 세팅
# =============================================
def setup_test_users():
    print("[Setup] 테스트 유저 세팅 중...")
    conn = get_main_db()
    cur  = conn.cursor()
    now  = datetime.now()

    for user in GROUND_TRUTH_USERS:
        cur.execute("""
            INSERT INTO user_profile (user_id, birth, sex, monthly_income)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                birth          = EXCLUDED.birth,
                sex            = EXCLUDED.sex,
                monthly_income = EXCLUDED.monthly_income
        """, (
            user["user_id"],
            user["profile"]["birth"],
            user["profile"]["sex"],
            user["profile"]["monthly_income"],
        ))

        cur.execute("DELETE FROM monthly_summary WHERE user_id = %s", (user["user_id"],))
        for s in user["monthly_summary"]:
            cur.execute("""
                INSERT INTO monthly_summary
                    (summary_id, user_id, year, month, category, amount, ratio, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                str(uuid.uuid4()).replace("-", "")[:26],
                user["user_id"], now.year, now.month,
                s["category"], s["amount"], s["ratio"], now,
            ))
        conn.commit()
        print(f"  ✅ {user['name']} ({user['user_id']})")

    cur.close()
    conn.close()


# =============================================
# LangGraph 파이프라인 실행 (리랭커 포함)
# =============================================
async def run_pipeline(user_id: str):
    result = await run_recommend_pipeline(user_id)
    if result.get("error"):
        raise RuntimeError(f"파이프라인 실패: {result['error']}")
    return result


# =============================================
# DB에서 추천 결과 조회
# =============================================
def fetch_recommend_results(user_id: str) -> dict:
    conn = get_main_db()
    cur  = conn.cursor()

    cur.execute("""
        SELECT cp.card_name FROM recommend_card rc
        JOIN card_product cp ON rc.card_product_id = cp.key
        WHERE rc.user_id = %s ORDER BY rc.created_at DESC
    """, (user_id,))
    cards = [r[0] for r in cur.fetchall()]

    cur.execute("""
        SELECT ip.insurance_name FROM recommend_insurance ri
        JOIN insurance_product ip ON ri.insurance_product_id = ip.key
        WHERE ri.user_id = %s ORDER BY ri.created_at DESC
    """, (user_id,))
    insurances = [r[0] for r in cur.fetchall()]

    cur.execute("""
        SELECT pp.policy_name FROM recommend_policy rp
        JOIN policy_product pp ON rp.policy_product_id = pp.key
        WHERE rp.user_id = %s ORDER BY rp.created_at DESC
    """, (user_id,))
    policies = [r[0] for r in cur.fetchall()]

    cur.close()
    conn.close()
    return {"cards": cards, "insurances": insurances, "policies": policies}


# =============================================
# 평가 지표
# =============================================
def hit_rate(rec, gt, k):
    return sum(1 for i in rec[:k] if i in gt) / len(gt) if gt else 0.0

def precision_at_k(rec, gt, k):
    return sum(1 for i in rec[:k] if i in gt) / k if k > 0 else 0.0

def ndcg_at_k(rec, gt, k):
    dcg  = sum(1.0 / math.log2(i + 2) for i, item in enumerate(rec[:k]) if item in gt)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(gt), k)))
    return dcg / idcg if idcg > 0 else 0.0

def mrr(rec, gt):
    for i, item in enumerate(rec):
        if item in gt:
            return 1.0 / (i + 1)
    return 0.0

def evaluate_user(user, recommended, k=3):
    gt     = user["ground_truth"]
    scores = {}

    for pk in ["cards", "insurances", "policies"]:
        rec_names = recommended.get(pk, [])
        gt_names  = gt[pk]
        scores[pk] = {
            f"hit_rate@{k}":  round(hit_rate(rec_names, gt_names, k), 4),
            f"precision@{k}": round(precision_at_k(rec_names, gt_names, k), 4),
            f"ndcg@{k}":      round(ndcg_at_k(rec_names, gt_names, k), 4),
            "mrr":            round(mrr(rec_names, gt_names), 4),
            "recommended":    rec_names,
            "ground_truth":   gt_names,
            "hits":           [r for r in rec_names if r in gt_names],
        }

    avg_hit  = sum(scores[pk][f"hit_rate@{k}"]  for pk in ["cards","insurances","policies"]) / 3
    avg_prec = sum(scores[pk][f"precision@{k}"] for pk in ["cards","insurances","policies"]) / 3
    avg_ndcg = sum(scores[pk][f"ndcg@{k}"]      for pk in ["cards","insurances","policies"]) / 3
    avg_mrr  = sum(scores[pk]["mrr"]             for pk in ["cards","insurances","policies"]) / 3

    scores["overall"] = {
        f"avg_hit_rate@{k}":  round(avg_hit,  4),
        f"avg_precision@{k}": round(avg_prec, 4),
        f"avg_ndcg@{k}":      round(avg_ndcg, 4),
        "avg_mrr":            round(avg_mrr,  4),
    }
    return scores


# =============================================
# 출력
# =============================================
def print_result(user, scores, k):
    print(f"\n  [{user['name']}]")
    for label, pk in [("카드","cards"), ("보험","insurances"), ("정책","policies")]:
        s = scores[pk]
        print(f"    {label}:")
        print(f"      추천: {s['recommended']}")
        print(f"      정답: {s['ground_truth']}")
        print(f"      적중: {s['hits']}")
        print(f"      Hit Rate@{k}={s[f'hit_rate@{k}']:.4f} | "
              f"Precision@{k}={s[f'precision@{k}']:.4f} | "
              f"NDCG@{k}={s[f'ndcg@{k}']:.4f} | "
              f"MRR={s['mrr']:.4f}")
    ov = scores["overall"]
    print(f"    {'─'*45}")
    print(f"    전체 평균: "
          f"Hit Rate={ov[f'avg_hit_rate@{k}']:.4f} | "
          f"Precision={ov[f'avg_precision@{k}']:.4f} | "
          f"NDCG={ov[f'avg_ndcg@{k}']:.4f} | "
          f"MRR={ov['avg_mrr']:.4f}")


def print_full_comparison(stage3_overall):
    print("\n" + "="*65)
    print("📈 전체 단계별 성능 비교")
    print("="*65)
    print(f"  {'지표':<15} {'1단계':>8} {'2단계':>8} {'3단계':>8} "
          f"{'1→2':>8} {'2→3':>8} {'1→3':>8}")
    print(f"  {'-'*63}")

    metrics = [
        (f"Hit Rate@{K}",  f"hit_rate@{K}",  f"avg_hit_rate@{K}"),
        (f"Precision@{K}", f"precision@{K}", f"avg_precision@{K}"),
        (f"NDCG@{K}",      f"ndcg@{K}",      f"avg_ndcg@{K}"),
        ("MRR",            "mrr",            "avg_mrr"),
    ]

    for label, s1_key, s3_key in metrics:
        s1 = BASELINES["stage1"][s1_key]
        s2 = BASELINES["stage2"][s1_key]
        s3 = stage3_overall[s3_key]

        d12 = (s2 - s1) / s1 * 100 if s1 > 0 else 0
        d23 = (s3 - s2) / s2 * 100 if s2 > 0 else 0
        d13 = (s3 - s1) / s1 * 100 if s1 > 0 else 0

        print(f"  {label:<15} {s1:>8.4f} {s2:>8.4f} {s3:>8.4f} "
              f"{d12:>+7.1f}% {d23:>+7.1f}% {d13:>+7.1f}%")


# =============================================
# 메인
# =============================================
async def main():
    print("🚀 3단계 평가 - Ground Truth 기반 정량 평가")
    print(f"   방식: LangGraph + klue-cross-encoder-v1 리랭커")
    print(f"   K={K}, 유저 수={len(GROUND_TRUTH_USERS)}명")
    print(f"   시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    setup_test_users()

    all_results = {}
    all_overall = []

    print("\n[평가 시작]")
    for user in GROUND_TRUTH_USERS:
        print(f"\n  유저: {user['name']} - 파이프라인 실행 중...")
        try:
            await run_pipeline(user["user_id"])
        except Exception as e:
            print(f"  ❌ 실패: {e}")
            continue

        recommended = fetch_recommend_results(user["user_id"])
        print(f"  추천: 카드 {len(recommended['cards'])}개 / "
              f"보험 {len(recommended['insurances'])}개 / "
              f"정책 {len(recommended['policies'])}개")

        scores = evaluate_user(user, recommended, k=K)
        print_result(user, scores, K)

        all_results[user["user_id"]] = {"user_name": user["name"], "scores": scores}
        all_overall.append(scores["overall"])

    if not all_overall:
        print("❌ 평가 결과 없음")
        return

    total_hit  = sum(o[f"avg_hit_rate@{K}"]  for o in all_overall) / len(all_overall)
    total_prec = sum(o[f"avg_precision@{K}"] for o in all_overall) / len(all_overall)
    total_ndcg = sum(o[f"avg_ndcg@{K}"]      for o in all_overall) / len(all_overall)
    total_mrr  = sum(o["avg_mrr"]             for o in all_overall) / len(all_overall)

    stage3_overall = {
        f"avg_hit_rate@{K}":  round(total_hit,  4),
        f"avg_precision@{K}": round(total_prec, 4),
        f"avg_ndcg@{K}":      round(total_ndcg, 4),
        "avg_mrr":            round(total_mrr,  4),
    }

    print("\n" + "="*60)
    print("📊 3단계 - 전체 평균 (LangGraph + 리랭커)")
    print("="*60)
    print(f"  Hit Rate@{K}:   {total_hit:.4f}")
    print(f"  Precision@{K}:  {total_prec:.4f}")
    print(f"  NDCG@{K}:       {total_ndcg:.4f}")
    print(f"  MRR:            {total_mrr:.4f}")

    print_full_comparison(stage3_overall)

    final = {
        "timestamp":  datetime.now().isoformat(),
        "stage":      "3단계_LangGraph+리랭커",
        "k":          K,
        "user_count": len(GROUND_TRUTH_USERS),
        "per_user":   all_results,
        "overall":    stage3_overall,
        "vs_stage1":  {
            s1_key: {
                "stage1": BASELINES["stage1"][s1_key],
                "stage2": BASELINES["stage2"][s1_key],
                "stage3": stage3_overall[s3_key],
                "1→2_pct": round((BASELINES["stage2"][s1_key] - BASELINES["stage1"][s1_key])
                                 / BASELINES["stage1"][s1_key] * 100, 1),
                "2→3_pct": round((stage3_overall[s3_key] - BASELINES["stage2"][s1_key])
                                 / BASELINES["stage2"][s1_key] * 100, 1),
                "1→3_pct": round((stage3_overall[s3_key] - BASELINES["stage1"][s1_key])
                                 / BASELINES["stage1"][s1_key] * 100, 1),
            }
            for s1_key, s3_key in [
                (f"hit_rate@{K}",  f"avg_hit_rate@{K}"),
                (f"precision@{K}", f"avg_precision@{K}"),
                (f"ndcg@{K}",      f"avg_ndcg@{K}"),
                ("mrr",            "avg_mrr"),
            ]
        },
    }

    with open("stage3_eval_result.json", "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 결과 저장: stage3_eval_result.json")
    print(f"   종료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    asyncio.run(main())