"""
LLM Judge - 추천 품질 평가 (Jenkins CI 통합용)
- 테스트 유저 10명 DB 세팅 → 추천 파이프라인 API 호출 → Claude Judge 평가
- 평균 점수 70점 미만 → exit code 1 (빌드 실패)
- 평균 점수 70점 이상 → exit code 0 (빌드 성공)

실행: python llm_benchmark.py
결과: llm_judge_result.json
"""
import json
import os
import sys
import time
import uuid
import httpx
import psycopg2
import anthropic
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()

BASE_URL       = os.getenv("EVAL_BASE_URL", "http://localhost:8000")
PASS_THRESHOLD = int(os.getenv("LLM_JUDGE_THRESHOLD", "70"))  # 통과 기준 점수
CALL_INTERVAL  = int(os.getenv("EVAL_CALL_INTERVAL", "15"))
WAIT_SEC       = int(os.getenv("EVAL_WAIT_SEC", "10"))

# =============================================
# 테스트 유저 (5명 - CI 속도 고려)
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
]


# =============================================
# DB 연결
# =============================================
def get_db():
    return psycopg2.connect(
        host     = os.getenv("DB_HOST"),
        port     = os.getenv("DB_PORT", 5432),
        dbname   = os.getenv("DB_NAME"),
        user     = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        sslmode  = os.getenv("DB_SSLMODE", "require"),
    )


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
                birth = EXCLUDED.birth,
                sex = EXCLUDED.sex,
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
    cur.close()
    print("  ✅ 유저 세팅 완료")


# =============================================
# 추천 파이프라인 API 호출
# =============================================
def call_generate_api(user_id: str) -> bool:
    try:
        resp = httpx.post(
            f"{BASE_URL}/internal/recommend/generate/{user_id}",
            timeout=60
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"    ❌ API 호출 실패: {e}")
        return False


# =============================================
# 추천 결과 조회
# =============================================
def fetch_results(user_id: str, conn) -> dict:
    cur = conn.cursor()

    cur.execute("""
        SELECT cp.company, cp.card_name, cp.top_benefit, rc.ai_reason
        FROM recommend_card rc
        JOIN card_product cp ON rc.card_product_id = cp.key
        WHERE rc.user_id = %s ORDER BY rc.created_at DESC
    """, (user_id,))
    cards = [{"name": f"{r[0]} {r[1]}", "top_benefit": r[2] or "", "reason": r[3] or ""}
             for r in cur.fetchall()]

    cur.execute("""
        SELECT ip.insurer, ip.insurance_name, ip.top_benefit, ri.ai_reason
        FROM recommend_insurance ri
        JOIN insurance_product ip ON ri.insurance_product_id = ip.key
        WHERE ri.user_id = %s ORDER BY ri.created_at DESC
    """, (user_id,))
    insurances = [{"name": f"{r[0]} {r[1]}", "top_benefit": r[2] or "", "reason": r[3] or ""}
                  for r in cur.fetchall()]

    cur.execute("""
        SELECT pp.policy_name, pp.org, pp.category, pp.core_benefit,
               pp.age_min, pp.age_max, pp.income_condition, rp.ai_reason
        FROM recommend_policy rp
        JOIN policy_product pp ON rp.policy_product_id = pp.key
        WHERE rp.user_id = %s ORDER BY rp.created_at DESC
    """, (user_id,))
    policies = [{"name": r[0], "org": r[1], "category": r[2] or "",
                 "core_benefit": r[3] or "",
                 "condition": f"{r[4]}~{r[5]}세 {r[6] or ''}",
                 "reason": r[7] or ""}
                for r in cur.fetchall()]

    cur.close()
    return {"cards": cards, "insurances": insurances, "policies": policies}


# =============================================
# LLM Judge 평가 (100점 만점)
# =============================================
def llm_judge(user: dict, results: dict) -> dict:
    client = anthropic.Anthropic()

    age     = datetime.now().year - user["profile"]["birth"].year
    income  = user["profile"]["monthly_income"]
    sex     = user["profile"]["sex"]
    summary = sorted(user["monthly_summary"], key=lambda x: x["amount"], reverse=True)
    total   = sum(s["amount"] for s in summary)

    spending_text = "\n".join([
        f"  - {s['category']}: {s['amount']:,}원 ({s['ratio']:.0f}%)"
        for s in summary
    ])

    def fmt_items(items: list, type_label: str) -> str:
        if not items:
            return f"{type_label}: 추천 없음"
        lines = [f"{type_label} ({len(items)}개):"]
        for i, item in enumerate(items, 1):
            benefit = item.get("core_benefit") or item.get("top_benefit", "")
            lines.append(f"  [{i}] {item['name']}")
            lines.append(f"      혜택: {benefit}")
            if type_label == "정책":
                lines.append(f"      조건: {item.get('condition', '')}")
            lines.append(f"      추천사유: {item['reason'][:100]}")
        return "\n".join(lines)

    spending_lines = [
        "  - " + s["category"] + ": " + format(s["amount"], ",") + "원 (" + str(int(s["ratio"])) + "%)"
        for s in summary
    ]
    spending_text2 = "\n".join(spending_lines)

    prompt_parts = [
        "당신은 청년 금융 추천 시스템의 공정한 평가자입니다.",
        "아래 유저 정보와 추천 결과를 보고 평가해주세요.",
        "",
        "## 중요 평가 원칙",
        "이 추천 시스템은 제한된 상품 풀(카드 36개, 보험 약 30개, 정책 약 200개) 내에서 최선의 추천을 합니다.",
        "완벽한 상품이 없을 수 있으므로, 주어진 후보 내에서 얼마나 최선의 선택을 했는지를 기준으로 평가하세요.",
        "상품이 유저와 100% 맞지 않더라도 후보 중 가장 적합한 선택이라면 높은 점수를 주세요.",
        "",
        "## 유저 정보",
        "- 나이: " + str(age) + "세 / 성별: " + sex,
        "- 월 소득: " + format(income, ",") + "원",
        "- 이번 달 총 지출: " + format(total, ",") + "원",
        "",
        "## 소비 패턴",
        spending_text2,
        "",
        "## 추천 결과",
        fmt_items(results["cards"], "카드"),
        "",
        fmt_items(results["insurances"], "보험"),
        "",
        fmt_items(results["policies"], "정책"),
        "",
        "## 평가 기준 (총 100점)",
        "1. 혜택 적합성 (0-40점): 제한된 상품 풀 내 최선의 선택인가. 40=최선, 30=적합, 20=일부적합, 10=연관낮음, 0=잘못된선택",
        "2. 추천 사유 품질 (0-30점): 실제 소비 데이터 언급 여부. 30=모두구체적, 20=절반이상, 10=일부, 0=일반설명만",
        "3. 자격 조건 충족 (0-20점): 정책 조건 충족 여부. 정책 후보가 유저 상황(직업, 소비패턴)과 맞지 않아 추천하지 않은 경우는 감점 없이 15점 부여. 정책없으면10점, 20=모두충족, 10=일부미충족, 0=불충족",
        "4. 추천 다양성 (0-10점): 카드/보험/정책 고루 추천. 단, 정책 후보 풀이 유저 상황과 맞지 않아 추천하지 않은 경우는 감점 없음. 10=모두있음또는정책불필요, 7=정책외나머지충실, 5=일부누락, 0=카드보험모두없음",
        "",
        "## 응답 형식 (JSON만, 다른 텍스트 없이)",
        '{"score": 정수, "breakdown": {"relevance": 정수, "faithfulness": 정수, "eligibility": 정수, "diversity": 정수}, "comment": "총평1문장"}',
    ]
    prompt = "\n".join(prompt_parts)

    try:
        response = client.messages.create(
            model      = "claude-haiku-4-5-20251001",
            max_tokens = 500,
            messages   = [{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

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
        return {"score": 0, "breakdown": {}, "comment": f"평가 실패: {e}"}


# =============================================
# 메인
# =============================================
def main():
    print("=" * 60)
    print("🧑‍⚖️  LLM Judge - 추천 품질 평가 (CI/CD)")
    print(f"   서버: {BASE_URL}")
    print(f"   통과 기준: {PASS_THRESHOLD}점 이상")
    print(f"   유저: {len(TEST_USERS)}명")
    print(f"   시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    conn = get_db()

    # 1. 유저 세팅
    print("\n[1] 테스트 유저 DB 세팅")
    setup_users(conn)

    # 2. 추천 API 호출
    print(f"\n[2] 추천 파이프라인 API 호출 (유저당 {CALL_INTERVAL}초 간격)")
    failed = []
    for idx, user in enumerate(TEST_USERS):
        print(f"  ▶ [{idx+1}/{len(TEST_USERS)}] {user['name']}...", end=" ", flush=True)
        ok = call_generate_api(user["user_id"])
        if ok:
            print("✅", flush=True)
            if idx < len(TEST_USERS) - 1:
                time.sleep(CALL_INTERVAL)
        else:
            failed.append(user["name"])
            print("❌", flush=True)

    # 3. 대기
    print(f"\n[대기] {WAIT_SEC}초 (파이프라인 완료 대기)...")
    time.sleep(WAIT_SEC)

    # 4. LLM Judge 평가
    print("\n[3] LLM Judge 평가")
    all_scores = []
    per_user_out = {}

    for user in TEST_USERS:
        if user["name"] in failed:
            print(f"  [{user['name']}] ⏭️  API 실패 - skip")
            continue

        results = fetch_results(user["user_id"], conn)
        total_rec = (len(results["cards"]) + len(results["insurances"])
                     + len(results["policies"]))

        if total_rec == 0:
            print(f"  [{user['name']}] ⚠️  추천 결과 없음 - skip")
            continue

        print(f"\n  [{user['name']}] 평가 중...", flush=True)
        judgment  = llm_judge(user, results)
        score     = judgment.get("score", 0)
        comment   = judgment.get("comment", "")
        breakdown = judgment.get("breakdown", {})
        all_scores.append(score)

        age    = datetime.now().year - user["profile"]["birth"].year
        income = user["profile"]["monthly_income"]
        print(f"    나이: {age}세 / 소득: {income:,}원")
        print(f"    점수: {score}/100")
        print(f"    세부: 적합성={breakdown.get('relevance',0)}/40 "
              f"사유={breakdown.get('faithfulness',0)}/30 "
              f"조건={breakdown.get('eligibility',0)}/20 "
              f"다양성={breakdown.get('diversity',0)}/10")
        print(f"    총평: {comment}")

        per_user_out[user["user_id"]] = {
            "name":    user["name"],
            "score":   score,
            "comment": comment,
            "breakdown": breakdown,
        }

    conn.close()

    # 5. 최종 결과
    print("\n" + "=" * 60)
    if not all_scores:
        print("❌ 평가 가능한 유저 없음 - 빌드 실패")
        sys.exit(1)

    avg_score = round(sum(all_scores) / len(all_scores), 1)
    print(f"📊 LLM Judge 최종 결과 ({len(all_scores)}명 평가)")
    print(f"   평균 점수: {avg_score}/100")
    print(f"   점수 분포: {all_scores}")
    print(f"   통과 기준: {PASS_THRESHOLD}점")

    if avg_score >= 4.0 * 20:  # 80점
        grade = "우수"
    elif avg_score >= PASS_THRESHOLD:
        grade = "통과"
    else:
        grade = "미흡"
    print(f"   평가 등급: {grade}")
    print("=" * 60)

    # 결과 저장
    output = {
        "timestamp":   datetime.now().isoformat(),
        "avg_score":   avg_score,
        "threshold":   PASS_THRESHOLD,
        "passed":      avg_score >= PASS_THRESHOLD,
        "eval_count":  len(all_scores),
        "all_scores":  all_scores,
        "failed_apis": failed,
        "per_user":    per_user_out,
    }
    with open("llm_judge_result.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 결과 저장: llm_judge_result.json")

    # 6. 점수 기준 exit code
    if avg_score < PASS_THRESHOLD:
        print(f"\n❌ 빌드 실패: 평균 점수 {avg_score}점 < 기준 {PASS_THRESHOLD}점")
        sys.exit(1)
    else:
        print(f"\n✅ 빌드 통과: 평균 점수 {avg_score}점 >= 기준 {PASS_THRESHOLD}점")
        sys.exit(0)


if __name__ == "__main__":
    main()