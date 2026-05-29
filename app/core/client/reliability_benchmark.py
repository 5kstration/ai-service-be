"""
1단계 기준선 측정 - Ground Truth 기반 정량 평가
순수 벡터 유사도 검색만 사용 (LangGraph/리랭커/필터/conflict 없음)

측정 지표:
  - Hit Rate@K : 정답 상품이 추천 K개 안에 몇 개 포함됐는지
  - Precision@K: 추천 K개 중 정답 비율
  - NDCG@K     : 순위 가중치 포함 정확도 (정답이 상위일수록 높은 점수)
  - MRR        : 첫 번째 정답이 몇 위에 나왔는지

실행: python baseline_eval.py
결과: baseline_eval_result.json
"""
import json
import math
import os
import psycopg2
import boto3
from datetime import date, datetime
from dotenv import load_dotenv
import uuid

load_dotenv()

# =============================================
# Ground Truth 정의
# 유저 타입별로 정답 상품명을 미리 정의
# 실제 더미 데이터의 상품명 기준
# =============================================
GROUND_TRUTH_USERS = [
    {
        "user_id":   "01HXGT000000000001",
        "name":      "식비_교통_중심",
        "profile": {
            "birth":         date(1998, 1, 15),  # 28세
            "sex":           "남자",
            "monthly_income": 3500000,
        },
        "monthly_summary": [
            {"category": "식비",  "amount": 200000, "ratio": 45.0},
            {"category": "교통",  "amount": 120000, "ratio": 27.0},
            {"category": "카페",  "amount": 60000,  "ratio": 13.5},
            {"category": "쇼핑",  "amount": 40000,  "ratio": 9.0},
            {"category": "기타",  "amount": 24000,  "ratio": 5.5},
        ],
        "user_text": (
            "나이 28세 남자 청년 직장인. 월 소득 3,500,000원. "
            "이번 달 총 지출 444,000원. "
            "지출 상세: 식비 200,000원(45%), 교통 120,000원(27%), "
            "카페 60,000원(14%), 쇼핑 40,000원(9%), 기타 24,000원(5%). "
            "가장 많이 쓰는 카테고리: 식비, 교통. "
            "절약이 필요한 영역: 식비, 교통. "
            "관심 혜택: 배달앱 할인, 대중교통 할인, 청년정책, 금융혜택."
        ),
        # 이 유저에게 맞는 정답 상품명 (실제 더미 데이터 기준)
        "ground_truth": {
            "cards": [
                "신한 Deep Dream 카드",   # 배달앱 10% 할인 → 식비 많음
                "하나 1Q카드",            # 대중교통 20% 할인 → 교통비 많음
                "KB 청춘대로 TOK TOK카드", # 간편결제 10% 할인
            ],
            "insurances": [
                "삼성화재 애니핏 플러스",  # 걷기 운동 환급 → 교통(도보) 연관
                "현대해상 운전자보험 플러스", # 교통 지출 많음 → 운전자보험
            ],
            "policies": [
                "청년 교통비 지원",    # 교통비 120,000원 → 직접 연관
                "청년희망적금",        # 소득 조건 충족
                "내일배움카드",        # 청년 직장인
            ],
        }
    },
    {
        "user_id":   "01HXGT000000000002",
        "name":      "쇼핑_카페_중심",
        "profile": {
            "birth":         date(2000, 5, 20),  # 26세
            "sex":           "여자",
            "monthly_income": 2800000,
        },
        "monthly_summary": [
            {"category": "쇼핑",  "amount": 180000, "ratio": 42.0},
            {"category": "카페",  "amount": 100000, "ratio": 23.0},
            {"category": "식비",  "amount": 80000,  "ratio": 19.0},
            {"category": "문화",  "amount": 40000,  "ratio": 9.0},
            {"category": "기타",  "amount": 30000,  "ratio": 7.0},
        ],
        "user_text": (
            "나이 26세 여자 청년 직장인. 월 소득 2,800,000원. "
            "이번 달 총 지출 430,000원. "
            "지출 상세: 쇼핑 180,000원(42%), 카페 100,000원(23%), "
            "식비 80,000원(19%), 문화 40,000원(9%), 기타 30,000원(7%). "
            "가장 많이 쓰는 카테고리: 쇼핑, 카페. "
            "절약이 필요한 영역: 쇼핑, 카페. "
            "관심 혜택: 온라인쇼핑 할인, 카페 할인, 청년정책, 주거지원."
        ),
        "ground_truth": {
            "cards": [
                "NH올원 e카드",          # 온라인 가맹점 5% 캐시백 → 쇼핑 많음
                "신한 Deep Dream 카드",   # 카페 5% 할인 → 카페 많음
                "KB 청춘대로 TOK TOK카드", # 간편결제 할인 → 쇼핑 연관
            ],
            "insurances": [
                "삼성화재 애니핏 플러스",  # 26세 여성 적합
                "KB 암보험 다이렉트",      # 젊은 여성 암 보험
            ],
            "policies": [
                "청년 월세 지원",      # 26세 자취 가능성
                "청년희망적금",        # 소득 조건 충족
                "서울 청년 수당",      # 26세 소득 조건
            ],
        }
    },
    {
        "user_id":   "01HXGT000000000003",
        "name":      "저소득_주거_중심",
        "profile": {
            "birth":         date(1996, 8, 10),  # 30세
            "sex":           "남자",
            "monthly_income": 2200000,
        },
        "monthly_summary": [
            {"category": "주거",  "amount": 400000, "ratio": 50.0},
            {"category": "식비",  "amount": 150000, "ratio": 18.8},
            {"category": "교통",  "amount": 80000,  "ratio": 10.0},
            {"category": "통신",  "amount": 80000,  "ratio": 10.0},
            {"category": "기타",  "amount": 90000,  "ratio": 11.2},
        ],
        "user_text": (
            "나이 30세 남자 청년 직장인. 월 소득 2,200,000원. "
            "이번 달 총 지출 800,000원. "
            "지출 상세: 주거 400,000원(50%), 식비 150,000원(19%), "
            "교통 80,000원(10%), 통신 80,000원(10%), 기타 90,000원(11%). "
            "가장 많이 쓰는 카테고리: 주거, 식비. "
            "절약이 필요한 영역: 주거, 식비. "
            "관심 혜택: 주거지원, 월세지원, 청년정책, 실손보험."
        ),
        "ground_truth": {
            "cards": [
                "신한 Mr.Life 카드",       # 공과금/편의점 할인 → 주거비 연관
                "신한 Deep Dream 카드",    # 식비/배달 할인
                "하나 1Q카드",             # 교통 할인
            ],
            "insurances": [
                "라이프플러스 실손보험",    # 저소득 청년 실손 필요
                "현대해상 운전자보험 플러스", # 교통 지출 연관
            ],
            "policies": [
                "청년 월세 지원",          # 주거비 400,000원 → 직접 연관
                "청년 전세임대주택",        # 주거 지원 정책
                "청년 주거급여 분리지급",   # 저소득 주거 지원
            ],
        }
    },
]

# =============================================
# Bedrock 클라이언트
# =============================================
bedrock = boto3.client(
    "bedrock-runtime",
    region_name           = os.getenv("AWS_REGION", "ap-northeast-2"),
    aws_access_key_id     = os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY"),
)

def get_embedding(text: str) -> list[float]:
    response = bedrock.invoke_model(
        modelId     = "amazon.titan-embed-text-v2:0",
        contentType = "application/json",
        accept      = "application/json",
        body        = json.dumps({"inputText": text}),
    )
    return json.loads(response["body"].read())["embedding"]


# =============================================
# DB 연결
# =============================================
def get_vector_db():
    return psycopg2.connect(
        host     = os.getenv("VECTOR_DB_HOST"),
        port     = os.getenv("VECTOR_DB_PORT", 5432),
        dbname   = os.getenv("VECTOR_DB_NAME"),
        user     = os.getenv("VECTOR_DB_USER"),
        password = os.getenv("VECTOR_DB_PASSWORD"),
        sslmode  = os.getenv("DB_SSLMODE", "require"),
    )

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
# 테스트 유저 DB 세팅
# =============================================
def setup_test_users():
    """Ground Truth 유저들을 DB에 세팅."""
    print("[Setup] 테스트 유저 세팅 중...")
    conn = get_main_db()
    cur  = conn.cursor()
    now  = datetime.now()

    for user in GROUND_TRUTH_USERS:
        # user_profile upsert
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

        # monthly_summary 삭제 후 재삽입
        cur.execute(
            "DELETE FROM monthly_summary WHERE user_id = %s",
            (user["user_id"],)
        )

        for s in user["monthly_summary"]:
            cur.execute("""
                INSERT INTO monthly_summary
                    (summary_id, user_id, year, month, category, amount, ratio, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                str(uuid.uuid4()).replace("-", "")[:26],  # summary_id 직접 생성
                user["user_id"], now.year, now.month,
                s["category"], s["amount"], s["ratio"], now,
            ))
        conn.commit()
        print(f"  ✅ {user['name']} ({user['user_id']})")

    cur.close()
    conn.close()


# =============================================
# 순수 벡터 검색 추천
# =============================================
def vector_search_recommend(embedding: list[float], top_k: int = 5) -> dict:
    """타입별 상위 top_k개 벡터 검색."""
    emb_str = f"[{','.join(map(str, embedding))}]"
    vdb = get_vector_db()
    cur = vdb.cursor()

    results = {}
    for ptype in ["card", "insurance", "policy"]:
        cur.execute("""
            SELECT pe.product_id, pe.product_type,
                   1 - (pe.embedding <=> %s::vector) AS similarity
            FROM product_embedding pe
            WHERE pe.product_type = %s
            ORDER BY pe.embedding <=> %s::vector
            LIMIT %s
        """, (emb_str, ptype, emb_str, top_k))
        results[ptype] = [
            {"product_id": r[0], "similarity": float(r[2])}
            for r in cur.fetchall()
        ]

    cur.close()
    vdb.close()
    return results


def get_product_names(vector_results: dict) -> dict:
    """product_id → 상품명 변환."""
    conn = get_main_db()
    cur  = conn.cursor()
    named = {"card": [], "insurance": [], "policy": []}

    for item in vector_results["card"]:
        cur.execute(
            "SELECT card_name FROM card_product WHERE key = %s",
            (item["product_id"],)
        )
        row = cur.fetchone()
        if row:
            named["card"].append({
                "name": row[0], "similarity": item["similarity"]
            })

    for item in vector_results["insurance"]:
        cur.execute(
            "SELECT insurance_name FROM insurance_product WHERE key = %s",
            (item["product_id"],)
        )
        row = cur.fetchone()
        if row:
            named["insurance"].append({
                "name": row[0], "similarity": item["similarity"]
            })

    for item in vector_results["policy"]:
        cur.execute(
            "SELECT policy_name FROM policy_product WHERE key = %s",
            (item["product_id"],)
        )
        row = cur.fetchone()
        if row:
            named["policy"].append({
                "name": row[0], "similarity": item["similarity"]
            })

    cur.close()
    conn.close()
    return named


# =============================================
# 평가 지표 계산
# =============================================
def hit_rate(recommended: list[str], ground_truth: list[str], k: int) -> float:
    """Hit Rate@K: 정답 중 추천 k개 안에 포함된 비율."""
    recommended_k = recommended[:k]
    hits = sum(1 for item in recommended_k if item in ground_truth)
    return hits / len(ground_truth) if ground_truth else 0.0


def precision_at_k(recommended: list[str], ground_truth: list[str], k: int) -> float:
    """Precision@K: 추천 k개 중 정답 비율."""
    recommended_k = recommended[:k]
    hits = sum(1 for item in recommended_k if item in ground_truth)
    return hits / k if k > 0 else 0.0


def ndcg_at_k(recommended: list[str], ground_truth: list[str], k: int) -> float:
    """
    NDCG@K: 순위 가중치 포함 정확도.
    정답이 상위에 있을수록 높은 점수.
    """
    recommended_k = recommended[:k]

    # DCG: 실제 추천 순서 기준
    dcg = 0.0
    for i, item in enumerate(recommended_k):
        if item in ground_truth:
            dcg += 1.0 / math.log2(i + 2)  # i+2: 1-indexed + log2(1)=0 방지

    # IDCG: 이상적인 순서 기준 (정답이 모두 상위에 있을 때)
    idcg = 0.0
    for i in range(min(len(ground_truth), k)):
        idcg += 1.0 / math.log2(i + 2)

    return dcg / idcg if idcg > 0 else 0.0


def mrr(recommended: list[str], ground_truth: list[str]) -> float:
    """
    MRR (Mean Reciprocal Rank): 첫 번째 정답이 몇 위에 나왔는지.
    1위면 1.0, 2위면 0.5, 3위면 0.33...
    """
    for i, item in enumerate(recommended):
        if item in ground_truth:
            return 1.0 / (i + 1)
    return 0.0


def evaluate_user(user, recommended, k=3):
    gt     = user["ground_truth"]
    scores = {}

    for ptype, gt_key in [("card", "cards"), ("insurance", "insurances"), ("policy", "policies")]:
        rec_names = [r["name"] for r in recommended.get(ptype, [])]
        gt_names  = gt[gt_key]

        scores[gt_key] = {
            f"hit_rate@{k}":  round(hit_rate(rec_names, gt_names, k), 4),
            f"precision@{k}": round(precision_at_k(rec_names, gt_names, k), 4),
            f"ndcg@{k}":      round(ndcg_at_k(rec_names, gt_names, k), 4),
            "mrr":            round(mrr(rec_names, gt_names), 4),
            "recommended":    rec_names,
            "ground_truth":   gt_names,
            "hits":           [r for r in rec_names if r in gt_names],
        }

    # k를 ptype_key로 다른 변수명 사용
    avg_hit  = sum(scores[ptype_key][f"hit_rate@{k}"]  for ptype_key in ["cards","insurances","policies"]) / 3
    avg_prec = sum(scores[ptype_key][f"precision@{k}"] for ptype_key in ["cards","insurances","policies"]) / 3
    avg_ndcg = sum(scores[ptype_key][f"ndcg@{k}"]      for ptype_key in ["cards","insurances","policies"]) / 3
    avg_mrr  = sum(scores[ptype_key]["mrr"]             for ptype_key in ["cards","insurances","policies"]) / 3

    scores["overall"] = {
        f"avg_hit_rate@{k}":  round(avg_hit,  4),
        f"avg_precision@{k}": round(avg_prec, 4),
        f"avg_ndcg@{k}":      round(avg_ndcg, 4),
        "avg_mrr":            round(avg_mrr,  4),
    }

    return scores


# =============================================
# 결과 출력
# =============================================
def print_result(user: dict, scores: dict, k: int):
    print(f"\n  [{user['name']}]")
    for ptype, key in [("카드", "cards"), ("보험", "insurances"), ("정책", "policies")]:
        s = scores[key]
        print(f"    {ptype}:")
        print(f"      추천: {s['recommended']}")
        print(f"      정답: {s['ground_truth']}")
        print(f"      적중: {s['hits']}")
        print(f"      Hit Rate@{k}={s[f'hit_rate@{k}']:.4f} | "
              f"Precision@{k}={s[f'precision@{k}']:.4f} | "
              f"NDCG@{k}={s[f'ndcg@{k}']:.4f} | "
              f"MRR={s['mrr']:.4f}")
    ov = scores["overall"]
    print(f"    ─────────────────────────────────────────")
    print(f"    전체 평균: "
          f"Hit Rate={ov[f'avg_hit_rate@{k}']:.4f} | "
          f"Precision={ov[f'avg_precision@{k}']:.4f} | "
          f"NDCG={ov[f'avg_ndcg@{k}']:.4f} | "
          f"MRR={ov['avg_mrr']:.4f}")


# =============================================
# 메인
# =============================================
if __name__ == "__main__":
    K = 3  # 평가 기준 K값

    print("🚀 1단계 기준선 측정 - Ground Truth 기반 정량 평가")
    print(f"   방식: 순수 벡터 유사도 검색 (LangGraph/리랭커/필터 없음)")
    print(f"   K={K}, 유저 수={len(GROUND_TRUTH_USERS)}명")
    print(f"   시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 테스트 유저 DB 세팅
    setup_test_users()

    all_results = {}
    all_overall = []

    print("\n[평가 시작]")
    for user in GROUND_TRUTH_USERS:
        print(f"\n  유저: {user['name']} - 임베딩 생성 중...")
        embedding       = get_embedding(user["user_text"])
        vector_results  = vector_search_recommend(embedding, top_k=K)
        named_results   = get_product_names(vector_results)
        scores          = evaluate_user(user, named_results, k=K)

        print_result(user, scores, K)

        all_results[user["user_id"]] = {
            "user_name": user["name"],
            "scores":    scores,
        }
        all_overall.append(scores["overall"])

    # 전체 평균 (모든 유저)
    total_hit  = sum(o[f"avg_hit_rate@{K}"]  for o in all_overall) / len(all_overall)
    total_prec = sum(o[f"avg_precision@{K}"] for o in all_overall) / len(all_overall)
    total_ndcg = sum(o[f"avg_ndcg@{K}"]      for o in all_overall) / len(all_overall)
    total_mrr  = sum(o["avg_mrr"]             for o in all_overall) / len(all_overall)

    print("\n" + "="*60)
    print("📊 1단계 기준선 - 전체 평균 (순수 벡터 검색)")
    print("="*60)
    print(f"  Hit Rate@{K}:   {total_hit:.4f}  ← 정답 중 추천에 포함된 비율")
    print(f"  Precision@{K}:  {total_prec:.4f}  ← 추천 {K}개 중 정답 비율")
    print(f"  NDCG@{K}:       {total_ndcg:.4f}  ← 순위 가중 정확도 (1.0이 최고)")
    print(f"  MRR:            {total_mrr:.4f}  ← 첫 정답이 몇 위에 나왔는지")

    # 저장
    final = {
        "timestamp":  datetime.now().isoformat(),
        "stage":      "1단계_순수벡터검색",
        "k":          K,
        "user_count": len(GROUND_TRUTH_USERS),
        "per_user":   all_results,
        "overall": {
            f"hit_rate@{K}":   round(total_hit,  4),
            f"precision@{K}":  round(total_prec, 4),
            f"ndcg@{K}":       round(total_ndcg, 4),
            "mrr":             round(total_mrr,  4),
        },
    }

    with open("baseline_eval_result.json", "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 결과 저장: baseline_eval_result.json")
    print(f"   종료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n  → 이 수치가 1단계 기준선. 2단계(LangGraph) 동일 ground truth로 비교 예정.")