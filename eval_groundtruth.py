"""
추천 시스템 정량 평가 - Ground Truth 기반 Hit@K, Recall@K, NDCG@K
+ Cosine Similarity, ILD, Personalization, Faithfulness

Ground Truth 생성 룰 (엄격):
  정책: 나이조건 + 소득조건 + 카테고리/태그 매칭 (셋 다 만족)
  카드: 유저 TOP2 소비 카테고리 키워드가 benefits에 포함
  보험: 유저 라이프스타일 기반 타입 매칭 (특화 타입은 정확히 일치)

실행: python eval_groundtruth.py
결과: eval_gt_result.json
"""
import json
import math
import os
import re
import time
import uuid
import httpx
import psycopg2
import numpy as np
import boto3
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()

BASE_URL      = os.getenv("EVAL_BASE_URL", "http://localhost:8000")
WAIT_SEC      = int(os.getenv("EVAL_WAIT_SEC", "15"))
CALL_INTERVAL = int(os.getenv("EVAL_CALL_INTERVAL", "20"))

# 2025년 1인가구 기준 중위소득 (월)
MEDIAN_INCOME_1P = 2_392_013

# =============================================
# 테스트 유저 (eval.py와 동일)
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

# 카테고리 → 정책 카테고리 매핑
POLICY_CAT_MAP = {
    "식비":   ["생활지원", "금융"],
    "교통":   ["생활지원", "교통지원", "교통"],
    "쇼핑":   ["생활지원", "금융"],
    "카페":   ["생활지원", "문화/여가"],
    "주거":   ["주거", "주거지원"],
    "의료":   ["건강"],
    "여행":   ["문화/여가"],
    "자동차": ["생활지원", "금융"],
    "문화":   ["문화/여가", "문화지원"],
    "교육":   ["교육/자기계발", "교육지원", "교육"],
    "사업":   ["취업/창업", "창업지원"],
    "투자":   ["금융", "금융지원", "자산형성"],
    "주유":   ["생활지원"],
    "통신":   ["생활지원"],
    "운동":   ["문화/여가", "건강"],
    "여가":   ["문화/여가"],
}

# 카드 혜택 키워드 매핑
CARD_BENEFIT_KEYWORDS = {
    "식비":   ["외식", "음식점", "배달", "식비", "편의점", "마트"],
    "교통":   ["교통", "대중교통", "버스", "지하철", "주유"],
    "쇼핑":   ["쇼핑", "백화점", "온라인", "쇼핑몰"],
    "카페":   ["카페", "커피", "스타벅스"],
    "주거":   ["주거", "관리비", "생활"],
    "의료":   ["병원", "약국", "의료", "건강"],
    "여행":   ["여행", "해외", "항공", "호텔", "공항"],
    "자동차": ["주유", "자동차", "주차", "카센터", "세차"],
    "문화":   ["영화", "공연", "OTT", "도서", "문화"],
    "교육":   ["교육", "학원", "자격증"],
    "사업":   ["비즈니스", "사업"],
    "투자":   ["적립", "포인트", "캐시백"],
    "주유":   ["주유", "기름"],
    "통신":   ["통신", "휴대폰"],
    "운동":   ["운동", "헬스", "스포츠"],
    "여가":   ["여가", "레저"],
}

# 보험 타입 매핑 (소비 카테고리 → 관련 보험 타입 키워드)
INSURANCE_TYPE_MAP = {
    "의료":   ["실손", "건강", "입원", "통원", "3대질병", "암"],
    "여행":   ["여행", "해외"],
    "자동차": ["자동차", "운전자", "교통사고"],
    "주유":   ["자동차", "운전자"],
    "운동":   ["건강", "실손"],
    "식비":   [],   # 특화 없음 → 일반 건강보험 허용
    "교통":   [],
    "쇼핑":   [],
    "카페":   [],
    "주거":   [],
    "문화":   [],
    "교육":   [],
    "사업":   [],
    "투자":   ["연금", "저축", "변액"],
    "통신":   [],
    "여가":   [],
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
# 소득 조건 파싱
# =============================================
def income_condition_met(condition: str, monthly_income: int) -> bool:
    """소득 조건 텍스트 파싱 → 충족 여부 반환."""
    if not condition:
        return True
    c = condition.strip()

    if any(x in c for x in ["제한없음", "기준 없음", "없음"]):
        return True

    # 중위소득 % 기반
    m = re.search(r"중위소득\s*(\d+)%\s*이하", c)
    if m:
        pct    = int(m.group(1))
        limit  = MEDIAN_INCOME_1P * pct / 100
        return monthly_income <= limit

    # 연소득 기반 → 월 환산
    m = re.search(r"연소득\s*([\d,]+)만?원\s*이하", c)
    if m:
        val = int(m.group(1).replace(",", ""))
        if val < 10000:
            val *= 10000   # "5천만원" → 50,000,000
        monthly_limit = val / 12
        return monthly_income <= monthly_limit

    # 총급여 기반
    m = re.search(r"총급여\s*([\d,]+)만?원\s*이하", c)
    if m:
        val = int(m.group(1).replace(",", ""))
        if val < 10000:
            val *= 10000
        monthly_limit = val / 12
        return monthly_income <= monthly_limit

    # 부부합산 → 개인 기준으로 절반
    m = re.search(r"부부합산\s*([\d,]+)만?원\s*이하", c)
    if m:
        val = int(m.group(1).replace(",", ""))
        if val < 10000:
            val *= 10000
        monthly_limit = val / 2 / 12
        return monthly_income <= monthly_limit

    # 소득분위, 예술활동 등 파싱 어려운 건 통과 처리
    return True


# =============================================
# Ground Truth 생성
# =============================================
def get_ground_truth(user: dict, conn) -> dict:
    """유저별 ground truth pool 생성 (엄격한 룰 기반)."""
    cur  = conn.cursor()
    age  = datetime.now().year - user["profile"]["birth"].year
    income = user["profile"]["monthly_income"]

    sorted_summary = sorted(user["monthly_summary"], key=lambda x: x["amount"], reverse=True)
    top_cats = [s["category"] for s in sorted_summary[:3]]
    top2_cats = top_cats[:2]

    # ── 정책 GT ──────────────────────────────
    # 나이 조건 + 소득 조건 + 카테고리 매칭 (셋 다)
    cur.execute("""
        SELECT key, policy_name, org, category, tags,
               age_min, age_max, income_condition
        FROM policy_product
        WHERE age_min <= %s AND age_max >= %s
    """, (age, age))
    all_policies = cur.fetchall()

    policy_gt = []
    for row in all_policies:
        key, name, org, cat, tags, age_min, age_max, inc_cond = row
        # 소득 조건
        if not income_condition_met(inc_cond or "", income):
            continue
        # 카테고리 매칭
        relevant_cats = []
        for uc in top2_cats:
            relevant_cats.extend(POLICY_CAT_MAP.get(uc, []))
        if cat and any(rc in cat for rc in relevant_cats):
            policy_gt.append(key)
            continue
        # 태그 매칭
        if tags:
            try:
                tag_list = json.loads(tags)
                for uc in top2_cats:
                    kws = CATEGORY_KEYWORDS.get(uc, [])
                    if any(kw in str(t) for t in tag_list for kw in kws):
                        policy_gt.append(key)
                        break
            except Exception:
                pass

    # ── 카드 GT ──────────────────────────────
    # TOP2 소비 카테고리 키워드가 benefits에 포함
    cur.execute("SELECT key, card_name, benefits FROM card_product")
    all_cards = cur.fetchall()

    card_gt = []
    for key, name, benefits in all_cards:
        benefit_text = ""
        if benefits:
            try:
                items = json.loads(benefits)
                benefit_text = " ".join(
                    f"{b.get('label','')} {b.get('value','')}"
                    for b in items if isinstance(b, dict)
                )
            except Exception:
                benefit_text = benefits

        matched = 0
        for cat in top2_cats:
            kws = CARD_BENEFIT_KEYWORDS.get(cat, [])
            if any(kw in benefit_text for kw in kws):
                matched += 1
        # TOP2 중 1개 이상 매칭
        if matched >= 1:
            card_gt.append(key)

    # ── 보험 GT ──────────────────────────────
    # 유저 라이프스타일 기반 타입 매칭
    cur.execute("SELECT key, insurance_name, top_benefit, benefits FROM insurance_product")
    all_ins = cur.fetchall()

    # 유저 소비에서 보험 관련 타입 추출
    ins_type_keywords = []
    for cat in top_cats:
        kws = INSURANCE_TYPE_MAP.get(cat, [])
        ins_type_keywords.extend(kws)
    ins_type_keywords = list(set(ins_type_keywords))

    ins_gt = []
    for key, name, top_benefit, benefits in all_ins:
        combined = f"{name or ''} {top_benefit or ''} {benefits or ''}"

        if not ins_type_keywords:
            # 특화 타입 없는 유저 → 일반 건강/종합보험만
            if any(kw in combined for kw in ["건강", "종합", "실손", "청년"]):
                ins_gt.append(key)
        else:
            # 특화 타입 매칭
            if any(kw in combined for kw in ins_type_keywords):
                ins_gt.append(key)

    cur.close()

    return {
        "policies": list(set(policy_gt)),
        "cards":    list(set(card_gt)),
        "insurances": list(set(ins_gt)),
    }


# =============================================
# 추천 결과 조회
# =============================================
def fetch_results(user_id: str, conn) -> dict:
    cur = conn.cursor()

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
    return {"cards": cards, "insurances": insurances, "policies": policies}


# =============================================
# Hit@K, Recall@K, NDCG@K
# =============================================
def calc_hit_at_k(recommended: list[str], gt: list[str]) -> float:
    """추천 목록에 gt 상품이 하나라도 있으면 1."""
    if not gt or not recommended:
        return 0.0
    return 1.0 if any(k in gt for k in recommended) else 0.0

def calc_recall_at_k(recommended: list[str], gt: list[str]) -> float:
    """gt 중 추천에 포함된 비율."""
    if not gt:
        return 0.0
    hits = sum(1 for k in recommended if k in gt)
    return round(hits / len(gt), 4)

def calc_ndcg_at_k(recommended: list[str], gt: list[str]) -> float:
    """NDCG@K: 정답이 앞에 나올수록 높은 점수."""
    if not gt or not recommended:
        return 0.0
    gt_set = set(gt)
    dcg  = sum(
        (1 / math.log2(i + 2)) for i, k in enumerate(recommended) if k in gt_set
    )
    # IDCG: 정답이 앞에 다 나왔을 때 최댓값
    ideal_hits = min(len(recommended), len(gt))
    idcg = sum(1 / math.log2(i + 2) for i in range(ideal_hits))
    return round(dcg / idcg, 4) if idcg > 0 else 0.0

def calc_ranking_metrics(results: dict, gt: dict) -> dict:
    metrics = {}
    for pk in ["cards", "insurances", "policies"]:
        rec_keys = [item["key"] for item in results[pk]]
        gt_keys  = gt[pk]
        metrics[pk] = {
            "hit@k":    calc_hit_at_k(rec_keys, gt_keys),
            "recall@k": calc_recall_at_k(rec_keys, gt_keys),
            "ndcg@k":   calc_ndcg_at_k(rec_keys, gt_keys),
            "gt_size":  len(gt_keys),
            "rec_size": len(rec_keys),
        }
    return metrics


# =============================================
# 유저 임베딩 (가중 평균)
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
    "여가":   "여가활동 레저 취미생활",
}

def _embed_single(text: str, client) -> np.ndarray:
    import json as _json
    resp   = client.invoke_model(
        modelId     = os.getenv("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0"),
        contentType = "application/json",
        accept      = "application/json",
        body        = _json.dumps({"inputText": text}),
    )
    result = _json.loads(resp["body"].read())
    vec    = np.array(result["embedding"], dtype=np.float32)
    norm   = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec

def embed_user(user: dict) -> np.ndarray:
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

    income_hint = "저소득 생활지원 청년지원금" if income < 2000000 else \
                  "중소득 청년정책 금융혜택"   if income < 3500000 else \
                  "고소득 자산형성 프리미엄"
    age_hint    = "대학생 청년 취업준비"    if age < 25 else \
                  "사회초년생 청년 자립"    if age < 30 else \
                  "청년 직장인 자산관리"

    embeddings, weights = [], []
    for s in summary:
        cat      = s["category"]
        ratio    = s["amount"] / total if total > 0 else 0.0
        keywords = BENEFIT_KEYWORD_MAP.get(cat, cat)
        text     = f"{keywords} {income_hint} {age_hint} {sex} 청년"
        emb      = _embed_single(text, client)
        embeddings.append(emb)
        weights.append(ratio)

    weighted = np.average(embeddings, axis=0, weights=weights)
    norm     = np.linalg.norm(weighted)
    return weighted / norm if norm > 0 else weighted


# =============================================
# pgvector 임베딩 조회
# =============================================
def fetch_product_embeddings(product_ids: list[str], vconn) -> dict[str, np.ndarray]:
    if not product_ids:
        return {}
    cur = vconn.cursor()
    cur.execute("""
        SELECT product_id, embedding::text
        FROM product_embedding
        WHERE product_id = ANY(%s)
    """, (product_ids,))
    rows = cur.fetchall()
    cur.close()
    result = {}
    for pid, emb_text in rows:
        if not emb_text:
            continue
        vec  = np.array([float(x) for x in emb_text.strip("[]").split(",")], dtype=np.float32)
        norm = np.linalg.norm(vec)
        result[pid] = vec / norm if norm > 0 else vec
    return result

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


# =============================================
# Cosine Similarity
# =============================================
def calc_cosine_scores(user_emb: np.ndarray, results: dict, emb_map: dict) -> dict:
    scores = {}
    for pk in ["cards", "insurances", "policies"]:
        sims = [cosine_sim(user_emb, emb_map[item["key"]])
                for item in results[pk] if item["key"] in emb_map]
        scores[pk] = {
            "avg": round(float(np.mean(sims)), 4) if sims else 0.0,
            "count": len(sims),
        }
    all_sims = [cosine_sim(user_emb, emb_map[item["key"]])
                for pk in ["cards","insurances","policies"]
                for item in results[pk] if item["key"] in emb_map]
    scores["overall_avg"] = round(float(np.mean(all_sims)), 4) if all_sims else 0.0
    return scores


# =============================================
# ILD (타입별)
# =============================================
def _ild_keys(keys: list[str], emb_map: dict) -> float:
    embs = [emb_map[k] for k in keys if k in emb_map]
    if len(embs) < 2:
        return 0.0
    dists = [1.0 - cosine_sim(embs[i], embs[j])
             for i in range(len(embs)) for j in range(i+1, len(embs))]
    return round(float(np.mean(dists)), 4)

def calc_ild(results: dict, emb_map: dict) -> dict:
    card_ild = _ild_keys([c["key"] for c in results["cards"]], emb_map)
    ins_ild  = _ild_keys([i["key"] for i in results["insurances"]], emb_map)
    pol_ild  = _ild_keys([p["key"] for p in results["policies"]], emb_map)
    vals     = [v for v in [card_ild, ins_ild, pol_ild] if v > 0]
    return {
        "cards": card_ild, "insurances": ins_ild, "policies": pol_ild,
        "overall": round(float(np.mean(vals)), 4) if vals else 0.0,
    }


# =============================================
# Faithfulness
# =============================================
def calc_faithfulness(results: dict, user_categories: list[str]) -> float:
    keywords = []
    for cat in user_categories:
        keywords.extend(CATEGORY_KEYWORDS.get(cat, [cat]))
    all_reasons = ([c["reason"] for c in results["cards"]]
                   + [i["reason"] for i in results["insurances"]]
                   + [p["reason"] for p in results["policies"]])
    if not all_reasons:
        return 0.0
    matched = sum(1 for r in all_reasons if any(kw in r for kw in keywords))
    return round(matched / len(all_reasons), 4)


# =============================================
# Personalization
# =============================================
def calc_personalization(user_result_keys: dict) -> float:
    user_ids = list(user_result_keys.keys())
    if len(user_ids) < 2:
        return 0.0
    jaccard_sims = []
    for i in range(len(user_ids)):
        for j in range(i+1, len(user_ids)):
            u1 = user_result_keys[user_ids[i]]
            u2 = user_result_keys[user_ids[j]]
            s1 = set(u1["card_keys"] + u1["ins_keys"] + u1["pol_keys"])
            s2 = set(u2["card_keys"] + u2["ins_keys"] + u2["pol_keys"])
            if not s1 and not s2:
                jaccard_sims.append(1.0)
            elif not s1 or not s2:
                jaccard_sims.append(0.0)
            else:
                jaccard_sims.append(len(s1 & s2) / len(s1 | s2))
    return round(1.0 - float(np.mean(jaccard_sims)), 4)


# =============================================
# DB 세팅
# =============================================
def setup_users(conn):
    cur = conn.cursor()
    now = datetime.now()
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
            """, (str(uuid.uuid4()).replace("-","")[:26],
                  u["user_id"], now.year, now.month,
                  s["category"], s["amount"], s["ratio"], now))
    conn.commit()
    cur.close()
    print("  ✅ 유저 세팅 완료")

def call_generate_api(user_id: str) -> bool:
    try:
        resp = httpx.post(f"{BASE_URL}/internal/recommend/generate/{user_id}", timeout=30)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"  ❌ {e}")
        return False


# =============================================
# 메인
# =============================================
def main():
    print("="*62)
    print("🚀 추천 시스템 정량 평가 (Ground Truth + Cosine + ILD + Personalization)")
    print(f"   서버: {BASE_URL}")
    print(f"   유저: {len(TEST_USERS)}명")
    print(f"   시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*62)

    conn  = get_main_db()
    vconn = get_vector_db()

    print("\n[1] 유저 세팅")
    setup_users(conn)

    print("\n[2] Ground Truth 생성")
    user_gts = {}
    for user in TEST_USERS:
        gt = get_ground_truth(user, conn)
        user_gts[user["user_id"]] = gt
        print(f"  {user['name']}: 카드 {len(gt['cards'])}개 / 보험 {len(gt['insurances'])}개 / 정책 {len(gt['policies'])}개")

    print("\n[3] 유저 임베딩 생성 (가중 평균)")
    user_embeddings = {}
    for user in TEST_USERS:
        user_embeddings[user["user_id"]] = embed_user(user)
        print(f"  ✅ {user['name']}")

    print(f"\n[4] API 순차 호출 (유저당 {CALL_INTERVAL}초 간격)")
    failed = []
    for idx, user in enumerate(TEST_USERS):
        print(f"  ▶ [{idx+1}/{len(TEST_USERS)}] {user['name']}...", end=" ", flush=True)
        ok = call_generate_api(user["user_id"])
        if ok:
            if idx < len(TEST_USERS) - 1:
                print(f"✅  ({CALL_INTERVAL}초 대기)", flush=True)
                time.sleep(CALL_INTERVAL)
            else:
                print("✅", flush=True)
        else:
            failed.append(user["name"])

    print(f"\n[대기] {WAIT_SEC}초...")
    for i in range(WAIT_SEC, 0, -5):
        print(f"  {i}초...", flush=True)
        time.sleep(5)

    print("\n[5] 평가")
    all_metrics = {
        "hit":    {"cards":[], "insurances":[], "policies":[]},
        "recall": {"cards":[], "insurances":[], "policies":[]},
        "ndcg":   {"cards":[], "insurances":[], "policies":[]},
    }
    all_cosines, all_faiths, all_ilds = [], [], []
    per_type_cosine = {"cards":[], "insurances":[], "policies":[]}
    user_result_keys = {}
    per_user_out = {}

    for user in TEST_USERS:
        if user["name"] in failed:
            continue

        results   = fetch_results(user["user_id"], conn)
        gt        = user_gts[user["user_id"]]
        user_emb  = user_embeddings[user["user_id"]]
        user_cats = [s["category"] for s in user["monthly_summary"]]

        all_keys = ([c["key"] for c in results["cards"]]
                    + [i["key"] for i in results["insurances"]]
                    + [p["key"] for p in results["policies"]])
        emb_map  = fetch_product_embeddings(all_keys, vconn)

        ranking = calc_ranking_metrics(results, gt)
        cosine  = calc_cosine_scores(user_emb, results, emb_map)
        ild     = calc_ild(results, emb_map)
        faith   = calc_faithfulness(results, user_cats)

        # 집계
        for pk in ["cards","insurances","policies"]:
            all_metrics["hit"][pk].append(ranking[pk]["hit@k"])
            all_metrics["recall"][pk].append(ranking[pk]["recall@k"])
            all_metrics["ndcg"][pk].append(ranking[pk]["ndcg@k"])
            if cosine[pk]["count"] > 0:
                per_type_cosine[pk].append(cosine[pk]["avg"])
        all_cosines.append(cosine["overall_avg"])
        all_faiths.append(faith)
        all_ilds.append(ild)

        user_result_keys[user["user_id"]] = {
            "card_keys": [c["key"] for c in results["cards"]],
            "ins_keys":  [i["key"] for i in results["insurances"]],
            "pol_keys":  [p["key"] for p in results["policies"]],
        }

        # 유저별 출력
        age    = datetime.now().year - user["profile"]["birth"].year
        top3   = sorted(user["monthly_summary"], key=lambda x: x["amount"], reverse=True)[:3]
        top_text = " / ".join([f"{s['category']} {s['amount']:,}원" for s in top3])
        print(f"\n  ── [{user['name']}] {age}세 / {top_text}")
        print(f"     GT:  카드 {len(gt['cards'])}개 / 보험 {len(gt['insurances'])}개 / 정책 {len(gt['policies'])}개")
        print(f"     추천: 카드 {len(results['cards'])}개 / 보험 {len(results['insurances'])}개 / 정책 {len(results['policies'])}개")
        for pk, label in [("cards","카드"),("insurances","보험"),("policies","정책")]:
            r = ranking[pk]
            print(f"     {label}  Hit={r['hit@k']:.2f}  Recall={r['recall@k']:.4f}  NDCG={r['ndcg@k']:.4f}")
        print(f"     Cosine={cosine['overall_avg']:.4f}  ILD={ild['overall']:.4f}  Faith={faith:.4f}")

        per_user_out[user["user_id"]] = {
            "name": user["name"],
            "gt_sizes": {pk: len(gt[pk]) for pk in ["cards","insurances","policies"]},
            "rec_sizes": {pk: len(results[pk]) for pk in ["cards","insurances","policies"]},
            "ranking": ranking,
            "cosine": cosine,
            "ild": ild,
            "faithfulness": faith,
        }

    # ── 전체 요약 ──
    n = len(all_cosines)
    personalization = calc_personalization(user_result_keys)

    avg = lambda lst: round(float(np.mean(lst)), 4) if lst else 0.0

    print("\n" + "="*62)
    print(f"📊 전체 평가 결과 ({n}명)")
    print("="*62)
    print(f"  [Hit@K]    카드={avg(all_metrics['hit']['cards']):.4f}  보험={avg(all_metrics['hit']['insurances']):.4f}  정책={avg(all_metrics['hit']['policies']):.4f}")
    print(f"  [Recall@K] 카드={avg(all_metrics['recall']['cards']):.4f}  보험={avg(all_metrics['recall']['insurances']):.4f}  정책={avg(all_metrics['recall']['policies']):.4f}")
    print(f"  [NDCG@K]   카드={avg(all_metrics['ndcg']['cards']):.4f}  보험={avg(all_metrics['ndcg']['insurances']):.4f}  정책={avg(all_metrics['ndcg']['policies']):.4f}")
    print()
    ild_overall = avg([d["overall"] for d in all_ilds if d["overall"] > 0])
    print(f"  [Cosine Similarity] 전체={avg(all_cosines):.4f}  카드={avg(per_type_cosine['cards']):.4f}  보험={avg(per_type_cosine['insurances']):.4f}  정책={avg(per_type_cosine['policies']):.4f}")
    print(f"  [ILD]              전체={ild_overall:.4f}")
    print(f"  [Personalization]  {personalization:.4f}")
    print(f"  [Faithfulness]     {avg(all_faiths):.4f}")
    print("="*62)

    if failed:
        print(f"\n  ⚠️  실패: {', '.join(failed)}")

    output = {
        "timestamp":   datetime.now().isoformat(),
        "eval_count":  n,
        "failed":      failed,
        "hit_at_k":    {pk: avg(all_metrics["hit"][pk])    for pk in ["cards","insurances","policies"]},
        "recall_at_k": {pk: avg(all_metrics["recall"][pk]) for pk in ["cards","insurances","policies"]},
        "ndcg_at_k":   {pk: avg(all_metrics["ndcg"][pk])   for pk in ["cards","insurances","policies"]},
        "avg_cosine":  avg(all_cosines),
        "ild_overall": ild_overall,
        "personalization": personalization,
        "faithfulness": avg(all_faiths),
        "per_user": per_user_out,
    }
    with open("eval_gt_result.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 결과 저장: eval_gt_result.json")
    print(f"   종료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    conn.close()
    vconn.close()


if __name__ == "__main__":
    main()