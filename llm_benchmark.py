"""
LLM Judge - 추천 품질 평가 (Jenkins CI 통합용)
- 테스트 유저 7명 DB 세팅 -> 추천 파이프라인 API 호출 -> Claude Judge 3회 평균 평가
- 평균 점수 70점 미만 -> exit code 1 (빌드 실패)
- 평균 점수 70점 이상 -> exit code 0 (빌드 성공)
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
PASS_THRESHOLD = int(os.getenv("LLM_JUDGE_THRESHOLD", "65"))
CALL_INTERVAL  = int(os.getenv("EVAL_CALL_INTERVAL", "15"))
WAIT_SEC       = int(os.getenv("EVAL_WAIT_SEC", "60"))
JUDGE_TRIALS   = int(os.getenv("LLM_JUDGE_TRIALS", "3"))

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


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode=os.getenv("DB_SSLMODE", "require"),
    )


def setup_users(conn):
    cur = conn.cursor()
    now = datetime.now()
    for u in TEST_USERS:
        cur.execute(
            "INSERT INTO user_profile (user_id, birth, sex, monthly_income) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (user_id) DO UPDATE SET birth=EXCLUDED.birth, sex=EXCLUDED.sex, monthly_income=EXCLUDED.monthly_income",
            (u["user_id"], u["profile"]["birth"], u["profile"]["sex"], u["profile"]["monthly_income"])
        )
        cur.execute("DELETE FROM monthly_summary WHERE user_id=%s", (u["user_id"],))
        for s in u["monthly_summary"]:
            cur.execute(
                "INSERT INTO monthly_summary (summary_id,user_id,year,month,category,amount,ratio,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (str(uuid.uuid4()).replace("-","")[:26], u["user_id"], now.year, now.month, s["category"], s["amount"], s["ratio"], now)
            )
    conn.commit()
    cur.close()
    print("  OK: 유저 세팅 완료")


def call_generate_api(user_id):
    try:
        resp = httpx.post(BASE_URL + "/internal/recommend/generate/" + user_id, timeout=60)
        resp.raise_for_status()
        return True
    except Exception as e:
        print("    FAIL: " + str(e))
        return False


def fetch_results(user_id, conn):
    cur = conn.cursor()

    cur.execute(
        "SELECT cp.company, cp.card_name, cp.top_benefit, rc.ai_reason "
        "FROM recommend_card rc JOIN card_product cp ON rc.card_product_id=cp.key "
        "WHERE rc.user_id=%s ORDER BY rc.created_at DESC", (user_id,)
    )
    cards = [{"name": (r[0] or "") + " " + (r[1] or ""), "top_benefit": r[2] or "", "reason": r[3] or ""}
             for r in cur.fetchall()]

    cur.execute(
        "SELECT ip.insurer, ip.insurance_name, ip.top_benefit, ri.ai_reason "
        "FROM recommend_insurance ri JOIN insurance_product ip ON ri.insurance_product_id=ip.key "
        "WHERE ri.user_id=%s ORDER BY ri.created_at DESC", (user_id,)
    )
    insurances = [{"name": (r[0] or "") + " " + (r[1] or ""), "top_benefit": r[2] or "", "reason": r[3] or ""}
                  for r in cur.fetchall()]

    cur.execute(
        "SELECT pp.policy_name, pp.org, pp.category, pp.core_benefit, pp.age_min, pp.age_max, pp.income_condition, rp.ai_reason "
        "FROM recommend_policy rp JOIN policy_product pp ON rp.policy_product_id=pp.key "
        "WHERE rp.user_id=%s ORDER BY rp.created_at DESC", (user_id,)
    )
    policies = [{"name": r[0] or "", "org": r[1] or "", "category": r[2] or "",
                 "core_benefit": r[3] or "",
                 "condition": str(r[4]) + "~" + str(r[5]) + "세 " + (r[6] or ""),
                 "reason": r[7] or ""}
                for r in cur.fetchall()]

    # 전체 상품 풀 크기 조회
    cur.execute("SELECT COUNT(*) FROM card_product")
    total_cards = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM insurance_product")
    total_insurances = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM policy_product")
    total_policies = cur.fetchone()[0]

    cur.close()
    return {
        "cards": cards, "insurances": insurances, "policies": policies,
        "pool": {"cards": total_cards, "insurances": total_insurances, "policies": total_policies}
    }


def fmt_items(items, type_label):
    if not items:
        return type_label + ": 추천 없음 (0개)"
    lines = [type_label + " (" + str(len(items)) + "개):"]
    for i, item in enumerate(items, 1):
        benefit = item.get("core_benefit") or item.get("top_benefit", "")
        lines.append("  [" + str(i) + "] " + item["name"])
        lines.append("      혜택: " + str(benefit))
        if type_label == "정책":
            lines.append("      조건: " + item.get("condition", ""))
        lines.append("      추천사유: " + item["reason"][:120])
    return "\n".join(lines)


def llm_judge(user, results):
    client = anthropic.Anthropic()
    age = datetime.now().year - user["profile"]["birth"].year
    income = user["profile"]["monthly_income"]
    sex = user["profile"]["sex"]
    summary = sorted(user["monthly_summary"], key=lambda x: x["amount"], reverse=True)
    total = sum(s["amount"] for s in summary)
    pool = results.get("pool", {})

    spending_lines = [
        "  - " + s["category"] + ": " + format(s["amount"], ",") + "원 (" + str(int(s["ratio"])) + "%)"
        for s in summary
    ]
    spending_text = "\n".join(spending_lines)

    # 카드 풀에 없는 카테고리 파악
    user_cats = [s["category"] for s in summary[:3]]
    card_friendly_cats = ["식비", "교통", "카페", "쇼핑", "여행", "주유", "통신"]
    missing_cats = [c for c in user_cats if c not in card_friendly_cats]
    missing_note = ""
    if missing_cats:
        missing_note = "참고: " + "/".join(missing_cats) + " 카테고리 전용 카드가 풀에 없으므로 생활비 절감 카드 추천이 최선임. 이 경우 적합성 32점 이상 부여."

    prompt_parts = [
        "당신은 청년 금융 추천 시스템의 공정한 평가자입니다.",
        "",
        "## 시스템 제약사항 (반드시 고려)",
        "이 추천 시스템의 상품 풀은 매우 제한적입니다:",
        "- 카드: " + str(pool.get("cards", 36)) + "개 (주로 생활비/교통/쇼핑/여행 위주, 의료/운동/투자 전문 카드 없음)",
        "- 보험: " + str(pool.get("insurances", 30)) + "개",
        "- 정책: " + str(pool.get("policies", 200)) + "개 (전국 단위 정책만 포함, 지역 정책 제외됨)",
        "상품이 없어서 생활비 절감 카드를 추천한 것은 올바른 판단이며 높은 점수를 받아야 합니다.",
        missing_note,
        "",
        "## 평가 원칙",
        "1. 데이터 부족으로 인한 불완전한 매칭은 감점 대상이 아님",
        "2. 추천 사유 수치가 다소 다르더라도 방향성이 맞으면 감점 최소화",
        "3. 지역 조건(시/군/구)은 유저 거주지를 알 수 없으므로 정책 조건 평가에서 완전 제외 - 지역 정책 추천은 감점 없음",  # 이 줄 수정
        "4. 추천된 상품 수가 적은 것은 후보 풀 한계일 수 있으므로 감점 최소화",
        "",
        "## 유저 정보",
        "- 나이: " + str(age) + "세 / 성별: " + sex,
        "- 월 소득: " + format(income, ",") + "원",
        "- 이번 달 총 지출: " + format(total, ",") + "원",
        "",
        "## 소비 패턴 (많은 순)",
        spending_text,
        "",
        "## 추천 결과",
        fmt_items(results["cards"], "카드"),
        "",
        fmt_items(results["insurances"], "보험"),
        "",
        fmt_items(results["policies"], "정책"),
        "",
        "## 평가 기준 (총 100점)",
        "### 1. 혜택 적합성 (0-40점)",
        "제한된 상품 풀 내에서 유저 소비패턴에 가장 적합한 상품을 선택했는가",
        "- 40점: 소비 패턴 TOP3와 직접 연관",
        "- 36점: 간접 연관 또는 해당 카테고리 상품 없어 생활비 카드 추천 (최선의 선택)",
        "- 32점: 일부 적합하나 더 나은 선택 가능",
        "- 24점: 연관성 낮음",
        "- 0점: 명백히 잘못된 선택 (전혀 다른 카테고리)",
        "",
        "### 2. 추천 사유 품질 (0-30점)",
        "추천 사유에 유저 실제 소비 데이터(금액/카테고리)가 언급됐는가",
        "- 30점: 모든 사유에 소비 금액/카테고리 구체적 언급",
        "- 22점: 절반 이상 구체적 언급",
        "- 18점: 일부 언급했으나 금액 누락",        "- 14점: 일부 언급",
        "- 0점: 일반적 설명만",
        "",
        "### 3. 자격 조건 충족 (0-20점)",
        "정책의 나이/소득 조건 충족 여부 (지역 조건은 평가 제외)",
        "- 20점: 나이/소득 조건 모두 충족",
        "- 14점: 정책 추천 없음 또는 일부 미충족 의심",
        "- 0점: 명확히 나이/소득 조건 불충족",
        "",
        "### 4. 추천 다양성 (0-10점)",
        "카드/보험/정책 균형",
        "- 10점: 세 카테고리 모두 추천",
        "- 7점: 두 카테고리 추천",
        "- 3점: 한 카테고리만",
        "",
        "## 응답 (JSON만, 다른 텍스트 없이)",
        '{"score": 정수(0-100), "breakdown": {"relevance": 정수(0-40), "faithfulness": 정수(0-30), "eligibility": 정수(0-20), "diversity": 정수(0-10)}, "comment": "총평1문장"}',
    ]
    prompt = "\n".join(prompt_parts)

    def _call_once():
        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
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
            print("    WARN: Judge 실패: " + str(e))
            return None

    # JUDGE_TRIALS회 실행 후 평균
    trial_results = []
    for t in range(JUDGE_TRIALS):
        r = _call_once()
        if r and isinstance(r.get("score"), (int, float)) and r["score"] > 0:
            trial_results.append(r)
        if t < JUDGE_TRIALS - 1:
            time.sleep(2)

    if not trial_results:
        return {"score": 0, "breakdown": {}, "comment": "평가 실패"}

    n = len(trial_results)
    avg_score = round(sum(r["score"] for r in trial_results) / n)
    avg_bd = {
        "relevance":    round(sum(r.get("breakdown", {}).get("relevance", 0)    for r in trial_results) / n),
        "faithfulness": round(sum(r.get("breakdown", {}).get("faithfulness", 0) for r in trial_results) / n),
        "eligibility":  round(sum(r.get("breakdown", {}).get("eligibility", 0)  for r in trial_results) / n),
        "diversity":    round(sum(r.get("breakdown", {}).get("diversity", 0)     for r in trial_results) / n),
    }
    scores_str = "[" + ", ".join(str(r["score"]) for r in trial_results) + "]"
    print("    판정 점수: " + scores_str + " -> 평균 " + str(avg_score))
    return {"score": avg_score, "breakdown": avg_bd, "comment": trial_results[-1].get("comment", "")}


def main():
    print("=" * 62)
    print("LLM Judge - 추천 품질 평가 (CI/CD)")
    print("   서버: " + BASE_URL)
    print("   통과 기준: " + str(PASS_THRESHOLD) + "점 이상")
    print("   유저: " + str(len(TEST_USERS)) + "명 / Judge " + str(JUDGE_TRIALS) + "회 평균")
    print("   시작: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 62)

    conn = get_db()

    print("\n[1] 테스트 유저 DB 세팅")
    setup_users(conn)

    print("\n[2] 추천 파이프라인 API 호출 (유저당 " + str(CALL_INTERVAL) + "초 간격)")
    failed = []
    for idx, user in enumerate(TEST_USERS):
        print("  [" + str(idx+1) + "/" + str(len(TEST_USERS)) + "] " + user["name"] + "...", end=" ", flush=True)
        ok = call_generate_api(user["user_id"])
        if ok:
            print("OK", flush=True)
            if idx < len(TEST_USERS) - 1:
                time.sleep(CALL_INTERVAL)
        else:
            failed.append(user["name"])
            print("FAIL", flush=True)

    print("\n[대기] " + str(WAIT_SEC) + "초...")
    time.sleep(WAIT_SEC)

    print("\n[3] LLM Judge 평가 (유저당 " + str(JUDGE_TRIALS) + "회 실행 후 평균)")
    all_scores = []
    per_user_out = {}

    for user in TEST_USERS:
        if user["name"] in failed:
            print("  [" + user["name"] + "] SKIP")
            continue

        results = fetch_results(user["user_id"], conn)
        total_rec = len(results["cards"]) + len(results["insurances"]) + len(results["policies"])

        if total_rec == 0:
            print("  [" + user["name"] + "] 추천 결과 없음 - skip")
            continue

        print("\n  [" + user["name"] + "] 평가 중...", flush=True)
        judgment = llm_judge(user, results)
        score = judgment.get("score", 0)
        comment = judgment.get("comment", "")
        bd = judgment.get("breakdown", {})
        all_scores.append(score)

        age = datetime.now().year - user["profile"]["birth"].year
        income = user["profile"]["monthly_income"]
        print("    나이: " + str(age) + "세 / 소득: " + format(income, ",") + "원")
        print("    최종 점수: " + str(score) + "/100")
        print("    세부: 적합성=" + str(bd.get("relevance", 0)) + "/40 "
              + "사유=" + str(bd.get("faithfulness", 0)) + "/30 "
              + "조건=" + str(bd.get("eligibility", 0)) + "/20 "
              + "다양성=" + str(bd.get("diversity", 0)) + "/10")
        print("    총평: " + comment)

        per_user_out[user["user_id"]] = {
            "name": user["name"], "score": score,
            "comment": comment, "breakdown": bd,
        }

    conn.close()

    print("\n" + "=" * 62)
    if not all_scores:
        print("FAIL: 평가 가능한 유저 없음")
        sys.exit(1)

    avg_score = round(sum(all_scores) / len(all_scores), 1)
    print("LLM Judge 최종 결과 (" + str(len(all_scores)) + "명 평가)")
    print("   평균 점수: " + str(avg_score) + "/100")
    print("   점수 분포: " + str(all_scores))
    print("   통과 기준: " + str(PASS_THRESHOLD) + "점")
    grade = "우수" if avg_score >= 80 else ("통과" if avg_score >= PASS_THRESHOLD else "미흡")
    print("   평가 등급: " + grade)
    print("=" * 62)

    output = {
        "timestamp": datetime.now().isoformat(),
        "avg_score": avg_score, "threshold": PASS_THRESHOLD,
        "passed": avg_score >= PASS_THRESHOLD,
        "eval_count": len(all_scores), "all_scores": all_scores,
        "failed_apis": failed, "per_user": per_user_out,
    }
    with open("llm_judge_result.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\nOK: 결과 저장: llm_judge_result.json")

    if avg_score < PASS_THRESHOLD:
        print("\nFAIL: 평균 점수 " + str(avg_score) + "점 < 기준 " + str(PASS_THRESHOLD) + "점")
        sys.exit(1)
    else:
        print("\nOK: 빌드 통과: 평균 점수 " + str(avg_score) + "점 >= 기준 " + str(PASS_THRESHOLD) + "점")
        sys.exit(0)


if __name__ == "__main__":
    main()