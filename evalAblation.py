"""
추천 시스템 단계별 성능 비교 (Ablation Study)
- Stage 1: 벡터 검색만
- Stage 2: 벡터 + Neo4j
- Stage 3: 벡터 + Neo4j + Reranker
- Stage 4: 벡터 + Neo4j + Reranker + 소득조건 필터 (전체)

각 스테이지별로 동일 유저 10명 API 호출 → 지표 측정 → 비교

실행: python eval_ablation.py
결과: eval_ablation_result.json

필요 환경변수 (graph.py에서 읽음):
  DISABLE_RERANK=true/false
  DISABLE_NEO4J=true/false
  DISABLE_INCOME_FILTER=true/false
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
import anthropic
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()

BASE_URL      = os.getenv("EVAL_BASE_URL", "http://localhost:8000")
CALL_INTERVAL = int(os.getenv("EVAL_CALL_INTERVAL", "20"))
WAIT_SEC      = int(os.getenv("EVAL_WAIT_SEC", "15"))

# =============================================
# 스테이지 정의
# =============================================
STAGES = [
    {
        "name":  "Stage 1: 벡터 검색만",
        "short": "Vector Only",
        "env":   {"DISABLE_NEO4J": "true", "DISABLE_RERANK": "true", "DISABLE_INCOME_FILTER": "true"},
        "desc":  "pgvector 코사인 유사도 기반 후보 30개 → LLM 직접 전달",
    },
    {
        "name":  "Stage 2: 벡터 + Neo4j",
        "short": "Vector + Neo4j",
        "env":   {"DISABLE_NEO4J": "false", "DISABLE_RERANK": "true", "DISABLE_INCOME_FILTER": "true"},
        "desc":  "벡터 검색 + Neo4j 그래프 컨텍스트(카테고리/충돌 관계) LLM 전달",
    },
    {
        "name":  "Stage 3: 벡터 + Neo4j + Reranker",
        "short": "Vector + Neo4j + Reranker",
        "env":   {"DISABLE_NEO4J": "false", "DISABLE_RERANK": "false", "DISABLE_INCOME_FILTER": "true"},
        "desc":  "벡터 30개 → CrossEncoder 리랭킹 7개 → Neo4j 컨텍스트 → LLM",
    },
    {
        "name":  "Stage 4: 전체 파이프라인",
        "short": "Full Pipeline",
        "env":   {"DISABLE_NEO4J": "false", "DISABLE_RERANK": "false", "DISABLE_INCOME_FILTER": "false"},
        "desc":  "벡터 → 리랭커 → 소득조건 필터 → Neo4j 컨텍스트 → LLM",
    },
]

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
# DB 연결
# =============================================
def get_main_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"), sslmode=os.getenv("DB_SSLMODE", "require"),
    )

def get_vector_db():
    return psycopg2.connect(
        host=os.getenv("VECTOR_DB_HOST", os.getenv("DB_HOST")),
        port=os.getenv("VECTOR_DB_PORT", os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("VECTOR_DB_NAME", os.getenv("DB_NAME")),
        user=os.getenv("VECTOR_DB_USER", os.getenv("DB_USER")),
        password=os.getenv("VECTOR_DB_PASSWORD", os.getenv("DB_PASSWORD")),
        sslmode=os.getenv("DB_SSLMODE", "require"),
    )

# =============================================
# 유저 임베딩
# =============================================
def _embed_single(text, client):
    import json as _j
    resp = client.invoke_model(
        modelId=os.getenv("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0"),
        contentType="application/json", accept="application/json",
        body=_j.dumps({"inputText": text, "dimensions": 256, "normalize": True}),
    )
    result = _j.loads(resp["body"].read())
    vec = np.array(result["embedding"], dtype=np.float32)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec

def embed_user(user):
    client = boto3.client(
        "bedrock-runtime", region_name=os.getenv("AWS_REGION", "ap-northeast-2"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
    summary = user["monthly_summary"]
    total   = sum(s["amount"] for s in summary)
    income  = user["profile"]["monthly_income"]
    age     = datetime.now().year - user["profile"]["birth"].year
    sex     = user["profile"]["sex"]

    income_hint = ("저소득 생활지원 청년지원금" if income < 2000000
                   else "중소득 청년정책 금융혜택" if income < 3500000
                   else "고소득 자산형성 프리미엄")
    age_hint = ("대학생 청년 취업준비" if age < 25
                else "사회초년생 청년 자립" if age < 30
                else "청년 직장인 자산관리")

    embeddings, weights = [], []
    for s in summary:
        cat = s["category"]
        ratio = s["amount"] / total if total > 0 else 0.0
        text = f"{BENEFIT_KEYWORD_MAP.get(cat, cat)} {income_hint} {age_hint} {sex} 청년"
        embeddings.append(_embed_single(text, client))
        weights.append(ratio)

    weighted = np.average(embeddings, axis=0, weights=weights)
    norm = np.linalg.norm(weighted)
    return weighted / norm if norm > 0 else weighted

# =============================================
# DB 세팅
# =============================================
def setup_users(conn):
    cur = conn.cursor()
    now = datetime.now()
    for u in TEST_USERS:
        cur.execute("""
            INSERT INTO user_profile (user_id, birth, sex, monthly_income)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (user_id) DO UPDATE SET
                birth=EXCLUDED.birth, sex=EXCLUDED.sex, monthly_income=EXCLUDED.monthly_income
        """, (u["user_id"], u["profile"]["birth"], u["profile"]["sex"], u["profile"]["monthly_income"]))
        cur.execute("DELETE FROM monthly_summary WHERE user_id=%s", (u["user_id"],))
        for s in u["monthly_summary"]:
            cur.execute("""
                INSERT INTO monthly_summary (summary_id,user_id,year,month,category,amount,ratio,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (str(uuid.uuid4()).replace("-","")[:26], u["user_id"],
                  now.year, now.month, s["category"], s["amount"], s["ratio"], now))
    conn.commit()
    cur.close()

# =============================================
# API 호출 (스테이지 플래그 헤더로 전달)
# =============================================
def call_generate_api(user_id: str, stage_env: dict) -> bool:
    try:
        # X-Stage-* 헤더로 서버에 플래그 전달
        headers = {f"X-{k}": v for k, v in stage_env.items()}
        resp = httpx.post(
            f"{BASE_URL}/internal/recommend/generate/{user_id}",
            headers=headers, timeout=60
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"    ❌ {e}")
        return False

# =============================================
# 추천 결과 조회
# =============================================
def fetch_results(user_id, conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT cp.key, cp.company, cp.card_name, cp.top_benefit, cp.benefits, rc.ai_reason
        FROM recommend_card rc JOIN card_product cp ON rc.card_product_id=cp.key
        WHERE rc.user_id=%s ORDER BY rc.created_at DESC
    """, (user_id,))
    cards = [{"key":r[0],"name":r[2],"top_benefit":r[3] or "","benefits":r[4] or "[]","reason":r[5] or ""} for r in cur.fetchall()]

    cur.execute("""
        SELECT ip.key, ip.insurer, ip.insurance_name, ip.top_benefit, ip.benefits, ri.ai_reason
        FROM recommend_insurance ri JOIN insurance_product ip ON ri.insurance_product_id=ip.key
        WHERE ri.user_id=%s ORDER BY ri.created_at DESC
    """, (user_id,))
    insurances = [{"key":r[0],"name":r[2],"top_benefit":r[3] or "","benefits":r[4] or "[]","reason":r[5] or ""} for r in cur.fetchall()]

    cur.execute("""
        SELECT pp.key, pp.policy_name, pp.org, pp.category, pp.core_benefit,
               pp.age_min, pp.age_max, pp.income_condition, pp.tags, rp.ai_reason
        FROM recommend_policy rp JOIN policy_product pp ON rp.policy_product_id=pp.key
        WHERE rp.user_id=%s ORDER BY rp.created_at DESC
    """, (user_id,))
    policies = [{"key":r[0],"name":r[1],"org":r[2],"category":r[3] or "","core_benefit":r[4] or "",
                 "age_min":r[5],"age_max":r[6],"income_condition":r[7] or "","tags":r[8] or "[]","reason":r[9] or ""} for r in cur.fetchall()]

    cur.close()
    return {"cards": cards, "insurances": insurances, "policies": policies}

# =============================================
# 임베딩 조회
# =============================================
def fetch_embeddings(product_ids, vconn):
    if not product_ids: return {}
    cur = vconn.cursor()
    cur.execute("SELECT product_id, embedding::text FROM product_embedding WHERE product_id=ANY(%s)", (product_ids,))
    rows = cur.fetchall()
    cur.close()
    result = {}
    for pid, emb_text in rows:
        if not emb_text: continue
        vec = np.array([float(x) for x in emb_text.strip("[]").split(",")], dtype=np.float32)
        norm = np.linalg.norm(vec)
        result[pid] = vec / norm if norm > 0 else vec
    return result

# =============================================
# 지표 계산
# =============================================
def cosine_sim(a, b): return float(np.dot(a, b))

def calc_cosine(user_emb, results, emb_map):
    all_sims = []
    for pk in ["cards","insurances","policies"]:
        for item in results[pk]:
            emb = emb_map.get(item["key"])
            if emb is not None:
                all_sims.append(cosine_sim(user_emb, emb))
    return round(float(np.mean(all_sims)), 4) if all_sims else 0.0

def calc_faithfulness(results, user_cats):
    keywords = []
    for cat in user_cats:
        keywords.extend(CATEGORY_KEYWORDS.get(cat, [cat]))
    all_reasons = ([c["reason"] for c in results["cards"]]
                   + [i["reason"] for i in results["insurances"]]
                   + [p["reason"] for p in results["policies"]])
    if not all_reasons: return 0.0
    matched = sum(1 for r in all_reasons if any(kw in r for kw in keywords))
    return round(matched / len(all_reasons), 4)

def calc_ild(results, emb_map):
    all_dists = []
    for pk in ["cards","insurances","policies"]:
        keys = [item["key"] for item in results[pk]]
        embs = [emb_map[k] for k in keys if k in emb_map]
        for i in range(len(embs)):
            for j in range(i+1, len(embs)):
                all_dists.append(1.0 - cosine_sim(embs[i], embs[j]))
    return round(float(np.mean(all_dists)), 4) if all_dists else 0.0

# =============================================
# LLM Judge (100점 만점)
# =============================================
def llm_judge_score(user, results) -> dict:
    client = anthropic.Anthropic()
    age    = datetime.now().year - user["profile"]["birth"].year
    income = user["profile"]["monthly_income"]
    summary = sorted(user["monthly_summary"], key=lambda x: x["amount"], reverse=True)
    spending_text = "\n".join([
        f"  - {s['category']}: {s['amount']:,}원 ({s['ratio']:.0f}%)"
        for s in summary
    ])

    def fmt(items, label):
        if not items:
            return f"{label}: 추천 없음 (0개)"
        lines = [f"{label} ({len(items)}개):"]
        for i, item in enumerate(items, 1):
            benefit = item.get("core_benefit") or item.get("top_benefit", "")
            name    = item.get("name", "")
            reason  = item.get("reason", "")[:80]
            lines.append(f"  [{i}] {name}")
            lines.append(f"      혜택: {benefit}")
            lines.append(f"      추천사유: {reason}")
        return "\n".join(lines)

    # conflict 정보
    conflict_policies = [
        p for p in results["policies"]
        if "중복" in p.get("reason", "") or "conflict" in p.get("reason", "").lower()
    ]

    prompt = f"""당신은 청년 금융 추천 시스템의 전문 평가자입니다.
아래 유저 정보와 추천 결과를 보고 4가지 기준으로 평가해주세요.

## 유저 정보
- 나이: {age}세 / 월 소득: {income:,}원

## 이번 달 소비 패턴 (많은 순)
{spending_text}

## 추천 결과
{fmt(results['cards'], '카드')}

{fmt(results['insurances'], '보험')}

{fmt(results['policies'], '정책')}

## 평가 기준 (총 100점)

### 1. 혜택 적합성 (0-40점)
- 유저의 TOP 소비 카테고리와 추천 상품의 핵심 혜택이 직접적으로 연관되는가
- 40점: 주요 소비 카테고리 모두 커버
- 30점: 주요 카테고리 절반 이상 커버
- 20점: 일부 연관 있음
- 10점: 연관성 낮음
- 0점: 전혀 관련 없음

### 2. 추천 사유 품질 (0-30점)
- 추천 사유가 유저의 실제 소비 금액/카테고리를 구체적으로 언급했는가
- 30점: 모든 사유에 소비 데이터 구체적 언급
- 20점: 절반 이상 구체적 언급
- 10점: 일부 언급
- 0점: 일반적 설명만

### 3. 자격 조건 충족 (0-20점)
- 추천된 정책의 나이/소득 조건을 유저가 충족하는가
- 정책 추천이 없으면 10점
- 20점: 모든 정책 조건 충족
- 10점: 일부 조건 미충족 의심
- 0점: 명확히 조건 불충족 정책 포함

### 4. 추천 다양성 (0-10점)
- 카드/보험/정책이 고르게 추천됐는가, 중복 상품 없는가
- 10점: 세 카테고리 모두 추천, 중복 없음
- 5점: 일부 카테고리 누락 또는 중복
- 0점: 한 카테고리만 추천 또는 전부 중복

## 응답 형식 (반드시 JSON만, 설명 없이)
{{
  "score": 총점(0-100 정수),
  "breakdown": {{
    "relevance": 혜택적합성점수(0-40 정수),
    "faithfulness": 추천사유품질점수(0-30 정수),
    "eligibility": 자격조건점수(0-20 정수),
    "diversity": 다양성점수(0-10 정수)
  }},
  "strengths": "잘된 점 1문장",
  "weaknesses": "개선 필요한 점 1문장",
  "comment": "총평 1문장"
}}"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if "```" in text:
            for part in text.split("```"):
                part = part.strip().lstrip("json").strip()
                try:
                    return json.loads(part)
                except Exception:
                    continue
        return json.loads(text)
    except Exception as e:
        print(f"    ⚠️  LLM Judge 실패: {e}")
        return {"score": 0, "breakdown": {}, "comment": "실패"}

# =============================================
# 스테이지별 평가 실행
# =============================================
def run_stage(stage, user_embeddings, conn, vconn):
    print(f"\n{'='*62}")
    print(f"  {stage['name']}")
    print(f"  설명: {stage.get('desc','')}")
    print(f"{'='*62}")

    # API 호출 + 응답시간 측정 (개선 4)
    failed = []
    latencies = []
    for idx, user in enumerate(TEST_USERS):
        print(f"  ▶ [{idx+1}/{len(TEST_USERS)}] {user['name']}...", end=" ", flush=True)
        start = time.time()
        ok = call_generate_api(user["user_id"], stage["env"])
        elapsed = round(time.time() - start, 2)
        if ok:
            latencies.append(elapsed)
            if idx < len(TEST_USERS) - 1:
                print(f"✅ {elapsed}s  ({CALL_INTERVAL}초)", flush=True)
                time.sleep(CALL_INTERVAL)
            else:
                print(f"✅ {elapsed}s", flush=True)
        else:
            failed.append(user["name"])

    print(f"  [대기] {WAIT_SEC}초...")
    time.sleep(WAIT_SEC)

    # 지표 계산
    all_cosines, all_faiths, all_ilds, all_llm = [], [], [], []
    all_relevance, all_faith_score, all_eligibility, all_diversity = [], [], [], []
    conflict_count = 0  # conflict 감지 횟수 (개선 3)

    for user in TEST_USERS:
        if user["name"] in failed:
            continue

        results   = fetch_results(user["user_id"], conn)
        user_emb  = user_embeddings[user["user_id"]]
        user_cats = [s["category"] for s in user["monthly_summary"]]

        all_keys = ([c["key"] for c in results["cards"]]
                    + [i["key"] for i in results["insurances"]]
                    + [p["key"] for p in results["policies"]])
        emb_map = fetch_embeddings(all_keys, vconn)

        cosine = calc_cosine(user_emb, results, emb_map)
        faith  = calc_faithfulness(results, user_cats)
        ild    = calc_ild(results, emb_map)

        # conflict 감지 횟수
        for p in results["policies"]:
            if any(kw in p.get("reason", "") for kw in ["중복", "conflict", "동시 신청"]):
                conflict_count += 1

        print(f"    [{user['name']}] LLM Judge 평가 중...", flush=True)
        judge     = llm_judge_score(user, results)
        llm_score = judge.get("score", 0)
        breakdown = judge.get("breakdown", {})

        all_cosines.append(cosine)
        all_faiths.append(faith)
        all_ilds.append(ild)
        all_llm.append(llm_score)
        all_relevance.append(breakdown.get("relevance", 0))
        all_faith_score.append(breakdown.get("faithfulness", 0))
        all_eligibility.append(breakdown.get("eligibility", 0))
        all_diversity.append(breakdown.get("diversity", 0))

        print(
            f"      Cosine={cosine:.4f}  Faith={faith:.4f}  ILD={ild:.4f}  "
            f"LLM={llm_score}/100  "
            f"[적합성={breakdown.get('relevance',0)}/40 "
            f"사유={breakdown.get('faithfulness',0)}/30 "
            f"조건={breakdown.get('eligibility',0)}/20 "
            f"다양성={breakdown.get('diversity',0)}/10]"
        )

    avg = lambda lst: round(float(np.mean(lst)), 4) if lst else 0.0
    avg_latency = round(float(np.mean(latencies)), 2) if latencies else 0.0

    return {
        "stage":          stage["short"],
        "cosine":         avg(all_cosines),
        "faithfulness":   avg(all_faiths),
        "ild":            avg(all_ilds),
        "llm_judge":      avg(all_llm),
        "breakdown": {
            "relevance":    avg(all_relevance),
            "faithfulness": avg(all_faith_score),
            "eligibility":  avg(all_eligibility),
            "diversity":    avg(all_diversity),
        },
        "avg_latency_sec": avg_latency,
        "conflict_detected": conflict_count,
        "failed":         failed,
    }

# =============================================
# 메인
# =============================================
def main():
    print("="*62)
    print("🔬 추천 시스템 단계별 성능 비교 (Ablation Study)")
    print(f"   서버: {BASE_URL}")
    print(f"   스테이지: {len(STAGES)}개")
    print(f"   시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*62)

    conn  = get_main_db()
    vconn = get_vector_db()

    print("\n[1] 유저 세팅")
    setup_users(conn)
    print("  ✅ 완료")

    print("\n[2] 유저 임베딩 생성")
    user_embeddings = {}
    for user in TEST_USERS:
        user_embeddings[user["user_id"]] = embed_user(user)
        print(f"  ✅ {user['name']}")

    print("\n[3] 스테이지별 평가 시작")
    print("  ⚠️  서버의 graph.py가 X-DISABLE_* 헤더를 읽도록 수정되어 있어야 합니다.")

    stage_results = []
    for stage in STAGES:
        result = run_stage(stage, user_embeddings, conn, vconn)
        stage_results.append(result)

    # 최종 비교표
    print("\n" + "="*80)
    print("📊 단계별 성능 비교")
    print("="*80)
    print(f"{'스테이지':<28} {'Cosine':>7} {'Faith':>7} {'ILD':>7} {'LLM':>6} {'적합성':>7} {'사유':>6} {'조건':>6} {'다양성':>6} {'Latency':>8} {'Conflict':>9}")
    print("-"*80)
    for r in stage_results:
        bd = r.get("breakdown", {})
        print(
            f"{r['stage']:<28} "
            f"{r['cosine']:>7.4f} "
            f"{r['faithfulness']:>7.4f} "
            f"{r['ild']:>7.4f} "
            f"{r['llm_judge']:>6.1f} "
            f"{bd.get('relevance',0):>7.1f} "
            f"{bd.get('faithfulness',0):>6.1f} "
            f"{bd.get('eligibility',0):>6.1f} "
            f"{bd.get('diversity',0):>6.1f} "
            f"{r['avg_latency_sec']:>7.2f}s "
            f"{r['conflict_detected']:>9}"
        )
    print("="*80)

    # 개선율 출력
    if len(stage_results) >= 2:
        base = stage_results[0]
        final = stage_results[-1]
        print(f"\n📈 개선율 (Stage 1 → Stage {len(stage_results)})")
        print(f"  LLM Judge:   {base['llm_judge']:.1f} → {final['llm_judge']:.1f}  "
              f"({'+'if final['llm_judge']>=base['llm_judge'] else ''}{final['llm_judge']-base['llm_judge']:.1f}점)")
        print(f"  Faithfulness: {base['faithfulness']:.4f} → {final['faithfulness']:.4f}  "
              f"({'+'if final['faithfulness']>=base['faithfulness'] else ''}{(final['faithfulness']-base['faithfulness'])*100:.1f}%p)")
        print(f"  ILD:          {base['ild']:.4f} → {final['ild']:.4f}  "
              f"({'+'if final['ild']>=base['ild'] else ''}{(final['ild']-base['ild'])*100:.1f}%p)")

    output = {
        "timestamp": datetime.now().isoformat(),
        "stages":    stage_results,
    }
    with open("eval_ablation_result.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 결과 저장: eval_ablation_result.json")
    print(f"   종료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    conn.close()
    vconn.close()

if __name__ == "__main__":
    main()