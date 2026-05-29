"""
CI 전용 LLM-as-Judge 평가 스크립트
실행: python ci_eval.py
목적: 실제 추천 파이프라인 실행 후 품질이 기준치 이상인지 검증
기준치 미달 시 sys.exit(1) → GitLab CI 배포 차단
"""
import asyncio
import json
import logging
import os
import sys
import psycopg2
import boto3
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================
# 설정
# =============================================
EVAL_PASS_THRESHOLD = float(os.getenv("EVAL_PASS_THRESHOLD", "0.75"))
TEST_USER_ID        = os.getenv("CI_TEST_USER_ID", "01HXCITEST000000001")

# =============================================
# Bedrock Claude 클라이언트
# =============================================
bedrock = boto3.client(
    "bedrock-runtime",
    region_name           = os.getenv("AWS_REGION", "ap-northeast-2"),
    aws_access_key_id     = os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY"),
)


# =============================================
# Step 1. 테스트 유저 더미 데이터 세팅
# =============================================
def setup_test_user():
    """CI용 테스트 유저 + 소비 데이터 세팅."""
    logger.info("[CI Eval] Step 1. 테스트 유저 세팅")

    conn = psycopg2.connect(
        host     = os.getenv("DB_HOST"),
        port     = os.getenv("DB_PORT", 5432),
        dbname   = os.getenv("DB_NAME"),
        user     = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        sslmode  = os.getenv("DB_SSLMODE", "require"),
    )
    cur = conn.cursor()

    # user_profile upsert
    cur.execute("""
        INSERT INTO user_profile (user_id, birth, sex, monthly_income)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            birth          = EXCLUDED.birth,
            sex            = EXCLUDED.sex,
            monthly_income = EXCLUDED.monthly_income
    """, (TEST_USER_ID, date(1998, 1, 15), "남자", 3500000))

    # 기존 monthly_summary 삭제 후 재삽입
    now = datetime.now()
    cur.execute("DELETE FROM monthly_summary WHERE user_id = %s", (TEST_USER_ID,))
    test_summary = [
        ("식비",   156000, 37.1),
        ("쇼핑",    89000, 21.1),
        ("카페",    68000, 16.1),
        ("교통",    45000, 10.7),
        ("기타",    63000, 15.0),
    ]
    for category, amount, ratio in test_summary:
        cur.execute("""
            INSERT INTO monthly_summary
                (user_id, year, month, category, amount, ratio, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (TEST_USER_ID, now.year, now.month, category, amount, ratio, now))

    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"[CI Eval] 테스트 유저 세팅 완료 - user_id={TEST_USER_ID}")


# =============================================
# Step 2. 추천 파이프라인 실행
# =============================================
async def run_pipeline():
    """실제 추천 파이프라인 실행."""
    logger.info("[CI Eval] Step 2. 추천 파이프라인 실행")
    from app.domain.recommend_ai.embed_service import embed_all_products
    from app.domain.recommend_ai.graph import run_recommend_pipeline

    # 임베딩 생성
    logger.info("[CI Eval] 상품 임베딩 생성 중...")
    embed_all_products()

    # 추천 실행
    logger.info(f"[CI Eval] 추천 파이프라인 실행 중 - user_id={TEST_USER_ID}")
    result = await run_recommend_pipeline(TEST_USER_ID)

    if result.get("error"):
        raise RuntimeError(f"추천 파이프라인 실패: {result['error']}")

    logger.info("[CI Eval] 추천 파이프라인 완료")
    return result


# =============================================
# Step 3. DB에서 추천 결과 조회
# =============================================
def fetch_recommend_results() -> dict:
    """DB에서 실제 추천 결과 조회."""
    logger.info("[CI Eval] Step 3. 추천 결과 조회")

    conn = psycopg2.connect(
        host     = os.getenv("DB_HOST"),
        port     = os.getenv("DB_PORT", 5432),
        dbname   = os.getenv("DB_NAME"),
        user     = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        sslmode  = os.getenv("DB_SSLMODE", "require"),
    )
    cur = conn.cursor()

    # 추천 카드
    cur.execute("""
        SELECT cp.card_name, rc.ai_reason
        FROM recommend_card rc
        JOIN card_product cp ON rc.card_product_id = cp.key
        WHERE rc.user_id = %s
        ORDER BY rc.created_at DESC
    """, (TEST_USER_ID,))
    cards = [{"name": r[0], "reason": r[1]} for r in cur.fetchall()]

    # 추천 보험
    cur.execute("""
        SELECT ip.insurance_name, ri.ai_reason
        FROM recommend_insurance ri
        JOIN insurance_product ip ON ri.insurance_product_id = ip.key
        WHERE ri.user_id = %s
        ORDER BY ri.created_at DESC
    """, (TEST_USER_ID,))
    insurances = [{"name": r[0], "reason": r[1]} for r in cur.fetchall()]

    # 추천 정책
    cur.execute("""
        SELECT pp.policy_name, rp.ai_reason
        FROM recommend_policy rp
        JOIN policy_product pp ON rp.policy_product_id = pp.key
        WHERE rp.user_id = %s
        ORDER BY rp.created_at DESC
    """, (TEST_USER_ID,))
    policies = [{"name": r[0], "reason": r[1]} for r in cur.fetchall()]

    cur.close()
    conn.close()

    logger.info(
        f"[CI Eval] 조회 완료 - "
        f"카드 {len(cards)}개 / 보험 {len(insurances)}개 / 정책 {len(policies)}개"
    )

    if not cards and not insurances and not policies:
        raise RuntimeError("추천 결과가 없습니다. 파이프라인이 정상 실행됐는지 확인하세요.")

    return {
        "cards":      cards,
        "insurances": insurances,
        "policies":   policies,
    }


# =============================================
# Step 4. Claude LLM-as-Judge 평가
# =============================================
USER_PROFILE = {
    "age":    28,
    "sex":    "남자",
    "income": 3500000,
    "summary": [
        {"category": "식비",  "amount": 156000, "ratio": 37},
        {"category": "쇼핑",  "amount": 89000,  "ratio": 21},
        {"category": "카페",  "amount": 68000,  "ratio": 16},
        {"category": "교통",  "amount": 45000,  "ratio": 11},
        {"category": "기타",  "amount": 63000,  "ratio": 15},
    ]
}


def judge(results: dict) -> dict:
    """Claude가 추천 결과를 평가."""
    logger.info("[CI Eval] Step 4. LLM-as-Judge 평가")

    cards_text      = "\n".join([f"- {c['name']}: {c['reason']}" for c in results["cards"]])
    insurances_text = "\n".join([f"- {i['name']}: {i['reason']}" for i in results["insurances"]])
    policies_text   = "\n".join([f"- {p['name']}: {p['reason']}" for p in results["policies"]])

    prompt = f"""당신은 금융 추천 시스템의 품질을 평가하는 엄격한 전문가입니다.
아래 유저 정보와 AI 추천 결과를 보고 5가지 기준으로 각각 1~5점을 매겨주세요.
점수를 후하게 주지 마세요. 기준을 엄격하게 적용하세요.

## 유저 프로필
- 나이: {USER_PROFILE['age']}세 / 성별: {USER_PROFILE['sex']}
- 월 소득: {USER_PROFILE['income']:,}원
- 이번 달 소비:
{chr(10).join([f"  - {s['category']}: {s['amount']:,}원 ({s['ratio']}%)" for s in USER_PROFILE['summary']])}

## 추천 결과

### 카드
{cards_text if cards_text else "추천 없음"}

### 보험
{insurances_text if insurances_text else "추천 없음"}

### 정책
{policies_text if policies_text else "추천 없음"}

## 평가 기준 (각 1~5점, 엄격하게)

1. **소비패턴반영도**: 유저의 실제 소비 데이터가 추천에 반영됐는가?
   - 5점: 모든 추천 사유에 실제 소비 금액이 명시되고 절약 예상액까지 계산됨
   - 4점: 소비 금액은 언급했지만 절약액 계산이 일부 누락
   - 3점: 카테고리만 언급하고 구체적 금액 없음
   - 2점: 유저 데이터 언급 없이 나이/성별 기반 일반 추천
   - 1점: 유저 소비 패턴과 완전히 무관한 추천

2. **추천사유구체성**: 추천 사유가 얼마나 구체적이고 개인화됐는가?
   - 5점: 실제 금액, 절약 효과, 조건 수치 모두 포함
   - 4점: 금액은 있지만 절약 효과 계산 일부 누락
   - 3점: 상품 정보는 포함하지만 유저 맞춤 설명 부족
   - 2점: 상품 혜택만 나열, 개인화 없음
   - 1점: 일반적 설명만, 개인화 전혀 없음

3. **상품다양성**: 추천 상품들이 서로 다른 혜택 카테고리를 커버하는가?
   - 5점: 카드/보험/정책 각각이 다른 소비 영역 커버, 중복 없음
   - 4점: 대부분 다른 영역, 일부 중복
   - 3점: 같은 카테고리 내 비슷한 혜택 2개 이상
   - 2점: 절반 이상 비슷한 혜택
   - 1점: 대부분 유저 소비와 무관하거나 동일 혜택

4. **조건적합성**: 추천된 상품/정책이 유저 조건에 맞는가?
   - 5점: 모든 추천이 조건 충족, 사유에 조건 명시
   - 4점: 조건 충족하지만 사유에 설명 누락
   - 3점: 일부 조건 미충족 가능성
   - 2점: 절반 이상 조건 불일치
   - 1점: 대부분 조건 맞지 않음

5. **전반적품질**: 실제 서비스로 사용할 수 있는 수준인가?
   - 5점: 즉시 실서비스 적용 가능
   - 4점: 소소한 개선 필요하지만 실용적
   - 3점: 절반 정도 유용
   - 2점: 대부분 유용하지 않음
   - 1점: 서비스 사용 불가 수준

## 응답 형식 (JSON만, 다른 텍스트 없이)
{{
  "소비패턴반영도": {{"점수": 0, "이유": "..."}},
  "추천사유구체성": {{"점수": 0, "이유": "..."}},
  "상품다양성":     {{"점수": 0, "이유": "..."}},
  "조건적합성":     {{"점수": 0, "이유": "..."}},
  "전반적품질":     {{"점수": 0, "이유": "..."}},
  "총점": 0,
  "총평": "..."
}}"""

    response = bedrock.invoke_model(
        modelId     = "anthropic.claude-3-haiku-20240307-v1:0",
        contentType = "application/json",
        accept      = "application/json",
        body        = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        1000,
            "temperature":       0.1,
            "messages":          [{"role": "user", "content": prompt}],
        }),
    )
    result = json.loads(response["body"].read())
    text   = result["content"][0]["text"].strip()

    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    return json.loads(text.strip())


# =============================================
# Step 5. 결과 저장 및 pass/fail 판단
# =============================================
def save_and_judge(scores: dict) -> bool:
    total     = scores["총점"]
    normalized = total / 25.0

    print("\n" + "="*60)
    print("📊 CI Eval 결과")
    print("="*60)
    print(f"  소비패턴반영도: {scores['소비패턴반영도']['점수']}점 - {scores['소비패턴반영도']['이유']}")
    print(f"  추천사유구체성: {scores['추천사유구체성']['점수']}점 - {scores['추천사유구체성']['이유']}")
    print(f"  상품다양성:     {scores['상품다양성']['점수']}점 - {scores['상품다양성']['이유']}")
    print(f"  조건적합성:     {scores['조건적합성']['점수']}점 - {scores['조건적합성']['이유']}")
    print(f"  전반적품질:     {scores['전반적품질']['점수']}점 - {scores['전반적품질']['이유']}")
    print(f"\n  총점: {total}/25점 (정규화: {normalized:.2f})")
    print(f"  총평: {scores['총평']}")
    print(f"\n  임계값: {EVAL_PASS_THRESHOLD}")

    # 결과 파일 저장 (GitLab artifact)
    result = {
        "timestamp":   datetime.now().isoformat(),
        "user_id":     TEST_USER_ID,
        "scores":      scores,
        "normalized":  normalized,
        "threshold":   EVAL_PASS_THRESHOLD,
        "passed":      normalized >= EVAL_PASS_THRESHOLD,
    }
    with open("ci_eval_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # GitLab dotenv 형식으로도 저장 (파이프라인 변수로 활용 가능)
    with open("ci_eval.env", "w") as f:
        f.write(f"EVAL_SCORE={normalized:.4f}\n")
        f.write(f"EVAL_PASSED={'true' if normalized >= EVAL_PASS_THRESHOLD else 'false'}\n")
        f.write(f"EVAL_TOTAL={total}\n")

    return normalized >= EVAL_PASS_THRESHOLD


# =============================================
# 메인 실행
# =============================================
async def main():
    print("🚀 CI LLM-as-Judge 평가 시작")
    print(f"   테스트 유저: {TEST_USER_ID}")
    print(f"   임계값: {EVAL_PASS_THRESHOLD}")
    print(f"   시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    try:
        # Step 1. 테스트 유저 세팅
        setup_test_user()

        # Step 2. 추천 파이프라인 실행
        await run_pipeline()

        # Step 3. 추천 결과 조회
        results = fetch_recommend_results()

        # Step 4. Claude 평가
        scores = judge(results)

        # Step 5. 결과 저장 및 pass/fail
        passed = save_and_judge(scores)

        if passed:
            print(f"\n✅ PASS - 배포 진행")
            sys.exit(0)
        else:
            print(f"\n❌ FAIL - 추천 품질 기준 미달 → 배포 차단")
            sys.exit(1)

    except Exception as e:
        logger.error(f"[CI Eval] 평가 실패 - error={e}")
        print(f"\n❌ ERROR - {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())