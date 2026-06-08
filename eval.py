"""
추천 시스템 정량 평가 - Cosine Similarity 기반
- 실제 API(POST /internal/recommend/generate/{user_id}) 호출
- pgvector에서 추천 상품 임베딩 조회
- 유저 임베딩 vs 추천 상품 임베딩 코사인 유사도 측정
- Faithfulness (추천 사유 키워드 매칭) 병행 측정

실행: python eval.py
결과: eval_result.json
"""
import json
import os
import time
import uuid
import httpx
import psycopg2
import numpy as np
import boto3
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()

# Jaccard Similarity 모듈 (같은 디렉토리에 jaccard_similarity.py 필요)
try:
    from jaccard_similarity import calc_jaccard_scores
except ImportError:
    def calc_jaccard_scores(user, results):
        return {"overall_avg": 0.0, "cards": {"avg":0.0,"count":0,"items":[]},
                "insurances": {"avg":0.0,"count":0,"items":[]},
                "policies": {"avg":0.0,"count":0,"items":[]}}

BASE_URL      = os.getenv("EVAL_BASE_URL", "http://localhost:8000")
WAIT_SEC      = int(os.getenv("EVAL_WAIT_SEC", "15"))
CALL_INTERVAL = int(os.getenv("EVAL_CALL_INTERVAL", "20"))


# =============================================
# 테스트 유저
# =============================================
TEST_USERS = [
    {
        "user_id": "01HXGT000000000001",
        "name":    "식비_교통_중심",
        "profile": {"birth": date(1998, 1, 15), "sex": "남자", "monthly_income": 3500000},
        "monthly_summary": [
            {"category": "식비",  "amount": 200000, "ratio": 45.0},
            {"category": "교통",  "amount": 120000, "ratio": 27.0},
            {"category": "카페",  "amount": 60000,  "ratio": 13.5},
            {"category": "쇼핑",  "amount": 40000,  "ratio": 9.0},
            {"category": "기타",  "amount": 24000,  "ratio": 5.5},
        ],
    },
    {
        "user_id": "01HXGT000000000002",
        "name":    "쇼핑_카페_중심",
        "profile": {"birth": date(2000, 5, 20), "sex": "여자", "monthly_income": 2800000},
        "monthly_summary": [
            {"category": "쇼핑",  "amount": 180000, "ratio": 42.0},
            {"category": "카페",  "amount": 100000, "ratio": 23.0},
            {"category": "식비",  "amount": 80000,  "ratio": 19.0},
            {"category": "문화",  "amount": 40000,  "ratio": 9.0},
            {"category": "기타",  "amount": 30000,  "ratio": 7.0},
        ],
    },
    {
        "user_id": "01HXGT000000000003",
        "name":    "저소득_주거_중심",
        "profile": {"birth": date(1996, 8, 10), "sex": "남자", "monthly_income": 2200000},
        "monthly_summary": [
            {"category": "주거",  "amount": 400000, "ratio": 50.0},
            {"category": "식비",  "amount": 150000, "ratio": 18.8},
            {"category": "교통",  "amount": 80000,  "ratio": 10.0},
            {"category": "통신",  "amount": 80000,  "ratio": 10.0},
            {"category": "기타",  "amount": 90000,  "ratio": 11.2},
        ],
    },
    {
        "user_id": "01HXGT000000000004",
        "name":    "취업준비_자기계발_중심",
        "profile": {"birth": date(2001, 3, 5), "sex": "여자", "monthly_income": 1500000},
        "monthly_summary": [
            {"category": "교육",  "amount": 150000, "ratio": 40.0},
            {"category": "식비",  "amount": 100000, "ratio": 26.7},
            {"category": "교통",  "amount": 60000,  "ratio": 16.0},
            {"category": "통신",  "amount": 40000,  "ratio": 10.7},
            {"category": "기타",  "amount": 25000,  "ratio": 6.6},
        ],
    },
    {
        "user_id": "01HXGT000000000005",
        "name":    "고소득_투자_중심",
        "profile": {"birth": date(1995, 11, 20), "sex": "남자", "monthly_income": 5500000},
        "monthly_summary": [
            {"category": "투자",  "amount": 300000, "ratio": 38.0},
            {"category": "식비",  "amount": 200000, "ratio": 25.3},
            {"category": "쇼핑",  "amount": 150000, "ratio": 19.0},
            {"category": "여가",  "amount": 80000,  "ratio": 10.1},
            {"category": "기타",  "amount": 60000,  "ratio": 7.6},
        ],
    },
    {
        "user_id": "01HXGT000000000006",
        "name":    "창업_IT_중심",
        "profile": {"birth": date(1997, 7, 15), "sex": "남자", "monthly_income": 3000000},
        "monthly_summary": [
            {"category": "사업",  "amount": 250000, "ratio": 45.5},
            {"category": "식비",  "amount": 120000, "ratio": 21.8},
            {"category": "교통",  "amount": 80000,  "ratio": 14.5},
            {"category": "통신",  "amount": 60000,  "ratio": 10.9},
            {"category": "기타",  "amount": 40000,  "ratio": 7.3},
        ],
    },
    {
        "user_id": "01HXGT000000000007",
        "name":    "문화_여가_중심",
        "profile": {"birth": date(1999, 9, 10), "sex": "여자", "monthly_income": 2500000},
        "monthly_summary": [
            {"category": "문화",  "amount": 180000, "ratio": 46.2},
            {"category": "식비",  "amount": 100000, "ratio": 25.6},
            {"category": "카페",  "amount": 60000,  "ratio": 15.4},
            {"category": "쇼핑",  "amount": 30000,  "ratio": 7.7},
            {"category": "기타",  "amount": 20000,  "ratio": 5.1},
        ],
    },
    {
        "user_id": "01HXGT000000000008",
        "name":    "건강_의료_중심",
        "profile": {"birth": date(1993, 4, 25), "sex": "여자", "monthly_income": 4000000},
        "monthly_summary": [
            {"category": "의료",  "amount": 250000, "ratio": 47.2},
            {"category": "식비",  "amount": 150000, "ratio": 28.3},
            {"category": "운동",  "amount": 70000,  "ratio": 13.2},
            {"category": "교통",  "amount": 40000,  "ratio": 7.5},
            {"category": "기타",  "amount": 20000,  "ratio": 3.8},
        ],
    },
    {
        "user_id": "01HXGT000000000009",
        "name":    "해외여행_글로벌_중심",
        "profile": {"birth": date(1996, 6, 30), "sex": "남자", "monthly_income": 4500000},
        "monthly_summary": [
            {"category": "여행",  "amount": 300000, "ratio": 50.0},
            {"category": "식비",  "amount": 150000, "ratio": 25.0},
            {"category": "쇼핑",  "amount": 90000,  "ratio": 15.0},
            {"category": "교통",  "amount": 40000,  "ratio": 6.7},
            {"category": "기타",  "amount": 20000,  "ratio": 3.3},
        ],
    },
    {
        "user_id": "01HXGT000000000010",
        "name":    "자동차_주유_중심",
        "profile": {"birth": date(1994, 12, 10), "sex": "남자", "monthly_income": 3800000},
        "monthly_summary": [
            {"category": "자동차", "amount": 280000, "ratio": 50.9},
            {"category": "식비",   "amount": 150000, "ratio": 27.3},
            {"category": "주유",   "amount": 70000,  "ratio": 12.7},
            {"category": "쇼핑",   "amount": 30000,  "ratio": 5.5},
            {"category": "기타",   "amount": 20000,  "ratio": 3.6},
        ],
    },
]

# =============================================
# Faithfulness 키워드 맵
# =============================================
CATEGORY_KEYWORDS = {
    "식비":   ["식비", "음식", "외식", "식당", "배달", "카페"],
    "교통":   ["교통", "버스", "지하철", "대중교통", "주유", "자동차"],
    "쇼핑":   ["쇼핑", "온라인", "구매", "백화점"],
    "카페":   ["카페", "커피", "음료"],
    "주거":   ["주거", "월세", "전세", "임대", "주택"],
    "의료":   ["의료", "병원", "건강", "치료", "보험"],
    "여행":   ["여행", "해외", "항공", "관광"],
    "자동차": ["자동차", "주유", "차량", "운전"],
    "문화":   ["문화", "공연", "영화", "예술", "도서"],
    "교육":   ["교육", "학습", "자격증", "훈련", "취업"],
    "사업":   ["창업", "사업", "비즈니스"],
    "투자":   ["투자", "자산", "저축", "연금", "적금"],
    "운동":   ["운동", "스포츠", "헬스"],
    "여가":   ["여가", "레저", "취미"],
    "통신":   ["통신", "휴대폰"],
    "주유":   ["주유", "기름"],
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

def get_vector_db():
    return psycopg2.connect(
        host     = os.getenv("VECTOR_DB_HOST",     os.getenv("DB_HOST")),
        port     = os.getenv("VECTOR_DB_PORT",     os.getenv("DB_PORT", 5432)),
        dbname   = os.getenv("VECTOR_DB_NAME",     os.getenv("DB_NAME")),
        user     = os.getenv("VECTOR_DB_USER",     os.getenv("DB_USER")),
        password = os.getenv("VECTOR_DB_PASSWORD", os.getenv("DB_PASSWORD")),
        sslmode  = os.getenv("DB_SSLMODE", "require"),
    )


# =============================================
# 카테고리 → 혜택 키워드 맵 (embed_node와 동일)
# =============================================
BENEFIT_KEYWORD_MAP = {
    "식비":   "외식할인 음식점할인 배달할인 식비절약 카페할인",
    "교통":   "대중교통할인 교통비지원 버스지하철 교통비절약",
    "쇼핑":   "쇼핑할인 쇼핑캐시백 온라인쇼핑 포인트적립",
    "카페":   "카페할인 커피할인 음료할인 카페적립",
    "주거":   "월세지원 전세대출 주거지원 주거비절약 임대주택",
    "의료":   "실손보험 의료비지원 건강보험 병원비절약",
    "여행":   "여행자보험 해외결제무료 항공마일리지 여행혜택",
    "자동차": "자동차보험 주유할인 운전자보험 차량비절약",
    "문화":   "문화누리카드 공연할인 문화비지원 여가혜택",
    "교육":   "자기계발지원 내일배움카드 교육비지원 자격증",
    "사업":   "창업지원 사업화자금 소상공인지원 비즈니스",
    "투자":   "연금저축 자산형성 적금혜택 재테크",
    "주유":   "주유할인 기름값절약 주유소혜택 차량비",
    "통신":   "통신비할인 휴대폰요금 통신비절약",
    "운동":   "스포츠강좌 헬스할인 체육시설 건강관리",
    "기타":   "생활비절약 청년지원 금융혜택",
}


# =============================================
# 유저 임베딩 생성 - 가중 평균 방식 (embed_node와 동일 로직)
# =============================================
def _embed_single(text: str, client) -> np.ndarray:
    import json as _json
    resp   = client.invoke_model(
        modelId     = os.getenv("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0"),
        contentType = "application/json",
        accept      = "application/json",
        body        = _json.dumps({
            "inputText": text,
            "dimensions": 256,      # ← 추가
            "normalize": True       # ← 추가
        }),
    )
    result = _json.loads(resp["body"].read())
    vec    = np.array(result["embedding"], dtype=np.float32)
    norm   = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def embed_text(user: dict) -> np.ndarray:
    """
    카테고리별 임베딩을 지출 비중(ratio)으로 가중 평균.
    embed_node와 동일한 로직.
    """
    client = boto3.client(
        "bedrock-runtime",
        region_name           = os.getenv("AWS_REGION", "ap-northeast-2"),
        aws_access_key_id     = os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

    summary  = user["monthly_summary"]
    total    = sum(s["amount"] for s in summary)
    income   = user["profile"]["monthly_income"]
    age      = datetime.now().year - user["profile"]["birth"].year
    sex      = user["profile"]["sex"]

    if income < 2000000:
        income_hint = "저소득 생활지원 청년지원금"
    elif income < 3500000:
        income_hint = "중소득 청년정책 금융혜택"
    else:
        income_hint = "고소득 자산형성 프리미엄"

    if age < 25:
        age_hint = "대학생 청년 취업준비"
    elif age < 30:
        age_hint = "사회초년생 청년 자립"
    else:
        age_hint = "청년 직장인 자산관리"

    embeddings = []
    weights    = []

    for s in summary:
        cat      = s["category"]
        amount   = s["amount"]
        ratio    = amount / total if total > 0 else 0.0
        keywords = BENEFIT_KEYWORD_MAP.get(cat, cat)

        # 카테고리 키워드 + 공통 컨텍스트
        text = f"{keywords} {income_hint} {age_hint} {sex} 청년"
        emb  = _embed_single(text, client)

        embeddings.append(emb)
        weights.append(ratio)

    if not embeddings:
        # fallback
        text = f"{income_hint} {age_hint} {sex} 청년정책 금융상품"
        return _embed_single(text, client)

    # 가중 평균 후 L2 정규화
    weighted = np.average(embeddings, axis=0, weights=weights)
    norm     = np.linalg.norm(weighted)
    return weighted / norm if norm > 0 else weighted


# =============================================
# DB 세팅
# =============================================
def setup_users():
    print("[Setup] 테스트 유저 세팅 중...")
    conn = get_main_db()
    cur  = conn.cursor()
    now  = datetime.now()

    for u in TEST_USERS:
        cur.execute("""
            INSERT INTO user_profile (user_id, birth, sex, monthly_income)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                birth = EXCLUDED.birth, sex = EXCLUDED.sex,
                monthly_income = EXCLUDED.monthly_income
        """, (u["user_id"], u["profile"]["birth"],
              u["profile"]["sex"], u["profile"]["monthly_income"]))

        cur.execute("DELETE FROM monthly_summary WHERE user_id = %s", (u["user_id"],))
        for s in u["monthly_summary"]:
            cur.execute("""
                INSERT INTO monthly_summary
                    (summary_id, user_id, year, month, category, amount, ratio, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (str(uuid.uuid4()).replace("-", "")[:26],
                  u["user_id"], now.year, now.month,
                  s["category"], s["amount"], s["ratio"], now))
        conn.commit()
        print(f"  ✅ {u['name']}")

    cur.close()
    conn.close()


# =============================================
# API 호출
# =============================================
def call_generate_api(user_id: str) -> bool:
    try:
        resp = httpx.post(f"{BASE_URL}/internal/recommend/generate/{user_id}", timeout=30)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"  ❌ {e}")
        return False


# =============================================
# 추천 결과 조회 (product_id + name + reason)
# =============================================
def fetch_results(user_id: str) -> dict:
    conn = get_main_db()
    cur  = conn.cursor()

    cur.execute("""
        SELECT cp.key, cp.company, cp.card_name, cp.top_benefit, cp.benefits, rc.ai_reason
        FROM recommend_card rc
        JOIN card_product cp ON rc.card_product_id = cp.key
        WHERE rc.user_id = %s ORDER BY rc.created_at DESC
    """, (user_id,))
    cards = [{"key": r[0], "company": r[1], "name": r[2],
              "top_benefit": r[3] or "", "benefits": r[4] or "[]",
              "reason": r[5] or ""} for r in cur.fetchall()]

    cur.execute("""
        SELECT ip.key, ip.insurer, ip.insurance_name, ip.top_benefit, ip.benefits, ri.ai_reason
        FROM recommend_insurance ri
        JOIN insurance_product ip ON ri.insurance_product_id = ip.key
        WHERE ri.user_id = %s ORDER BY ri.created_at DESC
    """, (user_id,))
    insurances = [{"key": r[0], "insurer": r[1], "name": r[2],
                   "top_benefit": r[3] or "", "benefits": r[4] or "[]",
                   "reason": r[5] or ""} for r in cur.fetchall()]

    cur.execute("""
        SELECT pp.key, pp.policy_name, pp.org, pp.category,
               pp.core_benefit, pp.age_min, pp.age_max,
               pp.income_condition, pp.tags, rp.ai_reason
        FROM recommend_policy rp
        JOIN policy_product pp ON rp.policy_product_id = pp.key
        WHERE rp.user_id = %s ORDER BY rp.created_at DESC
    """, (user_id,))
    policies = [{"key": r[0], "name": r[1], "org": r[2], "category": r[3] or "",
                 "core_benefit": r[4] or "", "age_min": r[5], "age_max": r[6],
                 "income_condition": r[7] or "", "tags": r[8] or "[]",
                 "reason": r[9] or ""} for r in cur.fetchall()]

    cur.close()
    conn.close()
    return {"cards": cards, "insurances": insurances, "policies": policies}


# =============================================
# pgvector에서 추천 상품 임베딩 조회
# =============================================
def fetch_product_embeddings(product_ids: list[str]) -> dict[str, np.ndarray]:
    if not product_ids:
        return {}
    conn = get_vector_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT product_id, embedding::text
        FROM product_embedding
        WHERE product_id = ANY(%s)
    """, (product_ids,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = {}
    for product_id, emb_text in rows:
        if not emb_text:
            continue
        # "[0.1, 0.2, ...]" 형태 파싱
        vec = np.array([float(x) for x in emb_text.strip("[]").split(",")], dtype=np.float32)
        norm = np.linalg.norm(vec)
        result[product_id] = vec / norm if norm > 0 else vec
    return result


# =============================================
# 코사인 유사도 계산
# =============================================
def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # 둘 다 L2 정규화 됐으면 dot = cosine sim


def calc_cosine_scores(user_emb: np.ndarray, results: dict, emb_map: dict) -> dict:
    scores = {}
    for pk in ["cards", "insurances", "policies"]:
        sims = []
        for item in results[pk]:
            emb = emb_map.get(item["key"])
            if emb is not None:
                sims.append(cosine_similarity(user_emb, emb))
        scores[pk] = {
            "avg":   round(float(np.mean(sims)), 4) if sims else 0.0,
            "min":   round(float(np.min(sims)),  4) if sims else 0.0,
            "max":   round(float(np.max(sims)),  4) if sims else 0.0,
            "count": len(sims),
        }
    all_sims = [
        s for pk in ["cards", "insurances", "policies"]
        for item in results[pk]
        for s in ([cosine_similarity(user_emb, emb_map[item["key"]])]
                  if item["key"] in emb_map else [])
    ]
    scores["overall_avg"] = round(float(np.mean(all_sims)), 4) if all_sims else 0.0
    return scores


# =============================================
# ILD (Intra-List Diversity)
# 한 유저에게 추천된 상품들이 얼마나 서로 다른가
# 높을수록 다양한 상품 추천
# =============================================
def _ild_for_keys(keys: list[str], emb_map: dict) -> float:
    """특정 상품 목록의 ILD 계산."""
    embs = [emb_map[k] for k in keys if k in emb_map]
    if len(embs) < 2:
        return 0.0
    distances = []
    for i in range(len(embs)):
        for j in range(i + 1, len(embs)):
            sim = float(np.dot(embs[i], embs[j]))
            distances.append(1.0 - sim)
    return round(float(np.mean(distances)), 4)


def calc_ild(results: dict, emb_map: dict) -> dict:
    """타입별 ILD 계산."""
    card_keys = [c["key"] for c in results["cards"]]
    ins_keys  = [i["key"] for i in results["insurances"]]
    pol_keys  = [p["key"] for p in results["policies"]]

    card_ild = _ild_for_keys(card_keys, emb_map)
    ins_ild  = _ild_for_keys(ins_keys,  emb_map)
    pol_ild  = _ild_for_keys(pol_keys,  emb_map)

    # 전체 평균 (타입별 평균)
    vals = [v for v in [card_ild, ins_ild, pol_ild] if v > 0]
    overall = round(float(np.mean(vals)), 4) if vals else 0.0

    return {
        "cards":     card_ild,
        "insurances": ins_ild,
        "policies":  pol_ild,
        "overall":   overall,
    }


# =============================================
# Faithfulness
# =============================================
def calc_faithfulness(results: dict, user_categories: list[str]) -> float:
    keywords = []
    for cat in user_categories:
        keywords.extend(CATEGORY_KEYWORDS.get(cat, [cat]))

    all_reasons = (
        [c["reason"] for c in results["cards"]]
        + [i["reason"] for i in results["insurances"]]
        + [p["reason"] for p in results["policies"]]
    )
    if not all_reasons:
        return 0.0
    matched = sum(1 for r in all_reasons if any(kw in r for kw in keywords))
    return round(matched / len(all_reasons), 4)


# =============================================
# 출력
# =============================================
def parse_benefits(raw: str) -> list[str]:
    try:
        items = json.loads(raw)
        if isinstance(items, list):
            return [f"{b.get('label','')} {b.get('value','')}" for b in items]
    except Exception:
        pass
    return []

def parse_tags(raw: str) -> list[str]:
    try:
        items = json.loads(raw)
        if isinstance(items, list):
            return [str(t) for t in items]
    except Exception:
        pass
    return []


def print_user_result(user: dict, results: dict, cosine: dict, faith: float):
    age = datetime.now().year - user["profile"]["birth"].year
    income = user["profile"]["monthly_income"]
    summary = user["monthly_summary"]
    sorted_s = sorted(summary, key=lambda x: x["amount"], reverse=True)
    top3_text = " / ".join([f"{s['category']} {s['amount']:,}원({s['ratio']:.0f}%)" for s in sorted_s[:3]])

    print(f"\n{'='*58}")
    print(f"  [{user['name']}]  {age}세 {user['profile']['sex']} / 월소득 {income:,}원")
    print(f"  TOP지출: {top3_text}")
    print(f"  Cosine avg={cosine['overall_avg']:.4f}  Faithfulness={faith:.4f}")
    print(f"{'='*58}")

    # 카드
    if results["cards"]:
        print(f"  📳 카드 추천 ({len(results['cards'])}개)")
        for i, c in enumerate(results["cards"]):
            sim = cosine["cards"]["avg"]
            benefits = parse_benefits(c["benefits"])
            print(f"    [{i+1}] {c['company']} {c['name']}")
            print(f"        핵심혜택: {c['top_benefit']}")
            if benefits:
                print(f"        혜택상세: {' | '.join(benefits[:3])}")
            print(f"        추천사유: {c['reason'][:60]}..." if len(c['reason']) > 60 else f"        추천사유: {c['reason']}")
            print(f"        cosine: {sim:.4f}")
    else:
        print(f"  📳 카드 추천 없음")

    # 보험
    if results["insurances"]:
        print(f"  🛡️  보험 추천 ({len(results['insurances'])}개)")
        for i, ins in enumerate(results["insurances"]):
            sim = cosine["insurances"]["avg"]
            benefits = parse_benefits(ins["benefits"])
            print(f"    [{i+1}] {ins['insurer']} {ins['name']}")
            print(f"        핵심혜택: {ins['top_benefit']}")
            if benefits:
                print(f"        혜택상세: {' | '.join(benefits[:3])}")
            print(f"        추천사유: {ins['reason'][:60]}..." if len(ins['reason']) > 60 else f"        추천사유: {ins['reason']}")
            print(f"        cosine: {sim:.4f}")
    else:
        print(f"  🛡️  보험 추천 없음")

    # 정책
    if results["policies"]:
        print(f"  📋 정책 추천 ({len(results['policies'])}개)")
        for i, p in enumerate(results["policies"]):
            sim = cosine["policies"]["avg"]
            tags = parse_tags(p["tags"])
            age_range = f"{p['age_min']}~{p['age_max']}세" if p["age_min"] and p["age_max"] else ""
            print(f"    [{i+1}] [{p['category']}] {p['name']} ({p['org']})")
            print(f"        핵심혜택: {p['core_benefit']}")
            print(f"        조건: {age_range} {p['income_condition']}")
            if tags:
                print(f"        태그: {' '.join(['#'+t for t in tags[:4]])}")
            print(f"        추천사유: {p['reason'][:60]}..." if len(p['reason']) > 60 else f"        추천사유: {p['reason']}")
            print(f"        cosine: {sim:.4f}")
    else:
        print(f"  📋 정책 추천 없음")




def calc_personalization(all_user_results: dict) -> float:
    """
    유저 간 추천 겹침 비율 기반 개인화 점수.
    Personalization = 1 - avg(Jaccard_similarity)
    1에 가까울수록 유저마다 다른 추천 (개인화 우수)
    """
    user_ids = list(all_user_results.keys())
    if len(user_ids) < 2:
        return 0.0

    jaccard_sims = []
    for i in range(len(user_ids)):
        for j in range(i + 1, len(user_ids)):
            u1 = all_user_results[user_ids[i]]
            u2 = all_user_results[user_ids[j]]

            set1 = set(u1.get("card_keys", []) + u1.get("ins_keys", []) + u1.get("pol_keys", []))
            set2 = set(u2.get("card_keys", []) + u2.get("ins_keys", []) + u2.get("pol_keys", []))

            if not set1 and not set2:
                jaccard_sims.append(1.0)
            elif not set1 or not set2:
                jaccard_sims.append(0.0)
            else:
                intersection = len(set1 & set2)
                union        = len(set1 | set2)
                jaccard_sims.append(intersection / union)

    avg_jaccard = float(np.mean(jaccard_sims))
    return round(1.0 - avg_jaccard, 4)


def print_summary(avg_cosine: float, avg_faith: float, per_type: dict,
                  ild_per_type: dict, ild_overall: float,
                  personalization: float, avg_jaccard: float,
                  per_type_jaccard: dict, n: int):
    print("\n" + "="*60)
    print(f"📊 전체 평가 결과 ({n}명)")
    print("="*60)
    print(f"  [Cosine Similarity] 유저 임베딩 vs 추천 상품 임베딩")
    print(f"    카드   avg: {per_type['cards']:.4f}")
    print(f"    보험   avg: {per_type['insurances']:.4f}")
    print(f"    정책   avg: {per_type['policies']:.4f}")
    print(f"    전체   avg: {avg_cosine:.4f}  (1.0에 가까울수록 유저 맞춤)")
    print()
    print(f"  [Overlap Coefficient] 유저 소비 키워드 vs 상품 혜택 키워드 매칭")
    print(f"    카드   avg: {per_type_jaccard['cards']:.4f}")
    print(f"    보험   avg: {per_type_jaccard['insurances']:.4f}")
    print(f"    정책   avg: {per_type_jaccard['policies']:.4f}")
    print(f"    전체   avg: {avg_jaccard:.4f}  (1.0에 가까울수록 키워드 매칭 우수)")
    print()
    print(f"  [ILD - Intra-List Diversity] 추천 목록 내 다양성")
    print(f"    카드   avg: {ild_per_type['cards']:.4f}")
    print(f"    보험   avg: {ild_per_type['insurances']:.4f}")
    print(f"    정책   avg: {ild_per_type['policies']:.4f}")
    print(f"    전체   avg: {ild_overall:.4f}  (1.0에 가까울수록 다양한 추천)")
    print()
    print(f"  [Personalization] 유저 간 추천 차별화")
    print(f"    avg: {personalization:.4f}  (1.0에 가까울수록 개인화 우수)")
    print()
    print(f"  [Faithfulness] 추천 사유 키워드 매칭")
    print(f"    avg: {avg_faith:.4f}  (1.0 = 모든 사유에 소비 맥락 언급)")
    print("="*60)


# =============================================
# 메인
# =============================================
def main():
    print("="*60)
    print("🚀 추천 시스템 정량 평가 (Cosine Similarity)")
    print(f"   서버: {BASE_URL}")
    print(f"   유저: {len(TEST_USERS)}명")
    print(f"   호출 간격: {CALL_INTERVAL}초 / 완료 대기: {WAIT_SEC}초")
    print(f"   예상 소요: {len(TEST_USERS) * CALL_INTERVAL + WAIT_SEC}초 (~{(len(TEST_USERS) * CALL_INTERVAL + WAIT_SEC) // 60}분)")
    print(f"   시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    setup_users()

    # 유저 임베딩 미리 생성
    print("\n[유저 임베딩 생성 중... (가중 평균 방식)]")
    user_embeddings = {}
    for user in TEST_USERS:
        user_embeddings[user["user_id"]] = embed_text(user)
        print(f"  ✅ {user['name']} ({len(user['monthly_summary'])}개 카테고리 가중 평균)")

    # API 순차 호출
    failed = []
    print(f"\n[API 호출] 유저당 {CALL_INTERVAL}초 간격")
    for idx, user in enumerate(TEST_USERS):
        print(f"  ▶ [{idx+1}/{len(TEST_USERS)}] {user['name']} - 호출 중...", end=" ", flush=True)
        ok = call_generate_api(user["user_id"])
        if ok:
            if idx < len(TEST_USERS) - 1:
                print(f"✅  ({CALL_INTERVAL}초 대기...)", flush=True)
                time.sleep(CALL_INTERVAL)
            else:
                print("✅", flush=True)
        else:
            print("❌")
            failed.append(user["name"])

    print(f"\n[대기] 마지막 파이프라인 완료까지 {WAIT_SEC}초...")
    for i in range(WAIT_SEC, 0, -5):
        print(f"  {i}초 남음...", flush=True)
        time.sleep(5)

    # 결과 수집 + 평가
    print("\n[평가]")
    all_cosines     = []
    all_faiths      = []
    all_ilds        = []
    all_jaccards    = []
    per_type_cosine  = {"cards": [], "insurances": [], "policies": []}
    per_type_jaccard = {"cards": [], "insurances": [], "policies": []}
    per_user_out    = {}
    user_result_keys = {}  # personalization 계산용

    for user in TEST_USERS:
        if user["name"] in failed:
            continue

        results    = fetch_results(user["user_id"])
        user_emb   = user_embeddings[user["user_id"]]
        user_cats  = [s["category"] for s in user["monthly_summary"]]

        # 추천된 상품 key 전체 수집
        all_keys = (
            [c["key"] for c in results["cards"]]
            + [i["key"] for i in results["insurances"]]
            + [p["key"] for p in results["policies"]]
        )
        emb_map = fetch_product_embeddings(all_keys)

        cosine  = calc_cosine_scores(user_emb, results, emb_map)
        faith   = calc_faithfulness(results, user_cats)
        ild     = calc_ild(results, emb_map)
        jaccard = calc_jaccard_scores(user, results)

        print_user_result(user, results, cosine, faith)

        all_cosines.append(cosine["overall_avg"])
        all_faiths.append(faith)
        all_ilds.append(ild)
        all_jaccards.append(jaccard["overall_avg"])
        for pk in ["cards", "insurances", "policies"]:
            if cosine[pk]["count"] > 0:
                per_type_cosine[pk].append(cosine[pk]["avg"])
            if jaccard[pk]["avg"] > 0:
                per_type_jaccard[pk].append(jaccard[pk]["avg"])

        # personalization 계산용 key 저장
        user_result_keys[user["user_id"]] = {
            "card_keys": [c["key"] for c in results["cards"]],
            "ins_keys":  [i["key"] for i in results["insurances"]],
            "pol_keys":  [p["key"] for p in results["policies"]],
        }

        per_user_out[user["user_id"]] = {
            "name":        user["name"],
            "profile":     f"{datetime.now().year - user['profile']['birth'].year}세 {user['profile']['sex']} / 월소득 {user['profile']['monthly_income']:,}원",
            "top_spending": [f"{s['category']} {s['amount']:,}원({s['ratio']:.0f}%)" for s in sorted(user['monthly_summary'], key=lambda x: x['amount'], reverse=True)[:3]],
            "cards": [
                {"name": c["name"], "company": c["company"],
                 "top_benefit": c["top_benefit"],
                 "reason": c["reason"], "cosine": round(cosine["cards"]["avg"], 4)}
                for c in results["cards"]
            ],
            "insurances": [
                {"name": ins["name"], "insurer": ins["insurer"],
                 "top_benefit": ins["top_benefit"],
                 "reason": ins["reason"], "cosine": round(cosine["insurances"]["avg"], 4)}
                for ins in results["insurances"]
            ],
            "policies": [
                {"name": p["name"], "org": p["org"], "category": p["category"],
                 "core_benefit": p["core_benefit"],
                 "condition": f"{p['age_min']}~{p['age_max']}세 {p['income_condition']}",
                 "reason": p["reason"], "cosine": round(cosine["policies"]["avg"], 4)}
                for p in results["policies"]
            ],
            "cosine_summary": cosine,
            "faithfulness":   faith,
        }

    if not all_cosines:
        print("❌ 평가된 유저 없음")
        return

    import numpy as np_fin
    avg_cosine = round(float(np_fin.mean(all_cosines)), 4)
    avg_faith  = round(float(np_fin.mean(all_faiths)),  4)
    avg_jaccard = round(float(np_fin.mean(all_jaccards)), 4)
    per_type_avg = {
        pk: round(float(np_fin.mean(v)), 4) if v else 0.0
        for pk, v in per_type_cosine.items()
    }
    per_type_jaccard_avg = {
        pk: round(float(np_fin.mean(v)), 4) if v else 0.0
        for pk, v in per_type_jaccard.items()
    }
    personalization = calc_personalization(user_result_keys)

    # ILD 타입별 평균
    ild_per_type = {}
    for pk in ["cards", "insurances", "policies"]:
        vals = [d[pk] for d in all_ilds if d[pk] > 0]
        ild_per_type[pk] = round(float(np_fin.mean(vals)), 4) if vals else 0.0
    ild_overall = round(float(np_fin.mean([d["overall"] for d in all_ilds if d["overall"] > 0])), 4)

    print_summary(avg_cosine, avg_faith, per_type_avg, ild_per_type, ild_overall,
                  personalization, avg_jaccard, per_type_jaccard_avg, len(all_cosines))

    if failed:
        print(f"\n  ⚠️  실패: {', '.join(failed)}")

    output = {
        "timestamp":             datetime.now().isoformat(),
        "server":                BASE_URL,
        "user_count":            len(TEST_USERS),
        "eval_count":            len(all_cosines),
        "failed":                failed,
        "avg_cosine_similarity": avg_cosine,
        "avg_faithfulness":      avg_faith,
        "ild_overall":           ild_overall,
        "ild_per_type":          ild_per_type,
        "personalization":       personalization,
        "per_type_cosine":       per_type_avg,
        "per_user":              per_user_out,
    }
    with open("eval_result.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 결과 저장: eval_result.json")
    print(f"   종료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()