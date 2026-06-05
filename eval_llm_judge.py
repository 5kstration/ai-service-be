"""
추천 시스템 LLM-as-Judge 평가
- 실제 Anthropic API (claude-haiku-4-5-20251001) 호출
- 유저 프로필 + 소비 패턴 + 추천 결과를 Claude에게 평가 요청
- 각 추천 항목별 1~5점 + 이유 생성
- 실제 API(POST /internal/recommend/generate/{user_id}) 호출

실행: python eval_llm_judge.py
결과: eval_llm_result.json
"""
import json
import os
import time
import uuid
import httpx
import psycopg2
import anthropic
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()

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


# =============================================
# 추천 결과 조회
# =============================================
def fetch_results(user_id: str, conn) -> dict:
    cur = conn.cursor()

    cur.execute("""
        SELECT cp.key, cp.company, cp.card_name, cp.top_benefit, rc.ai_reason
        FROM recommend_card rc
        JOIN card_product cp ON rc.card_product_id = cp.key
        WHERE rc.user_id = %s ORDER BY rc.created_at DESC
    """, (user_id,))
    cards = [{"name": f"{r[1]} {r[2]}", "top_benefit": r[3] or "", "reason": r[4] or ""}
             for r in cur.fetchall()]

    cur.execute("""
        SELECT ip.key, ip.insurer, ip.insurance_name, ip.top_benefit, ri.ai_reason
        FROM recommend_insurance ri
        JOIN insurance_product ip ON ri.insurance_product_id = ip.key
        WHERE ri.user_id = %s ORDER BY ri.created_at DESC
    """, (user_id,))
    insurances = [{"name": f"{r[1]} {r[2]}", "top_benefit": r[3] or "", "reason": r[4] or ""}
                  for r in cur.fetchall()]

    cur.execute("""
        SELECT pp.key, pp.policy_name, pp.org, pp.category, pp.core_benefit,
               pp.age_min, pp.age_max, pp.income_condition, rp.ai_reason
        FROM recommend_policy rp
        JOIN policy_product pp ON rp.policy_product_id = pp.key
        WHERE rp.user_id = %s ORDER BY rp.created_at DESC
    """, (user_id,))
    policies = [{"name": r[1], "org": r[2], "category": r[3] or "",
                 "core_benefit": r[4] or "",
                 "condition": f"{r[5]}~{r[6]}세 {r[7] or ''}",
                 "reason": r[8] or ""}
                for r in cur.fetchall()]

    cur.close()
    return {"cards": cards, "insurances": insurances, "policies": policies}


# =============================================
# LLM Judge 평가
# =============================================
def llm_judge(user: dict, results: dict) -> dict:
    """Anthropic API로 추천 결과 평가."""
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 자동 사용

    age     = datetime.now().year - user["profile"]["birth"].year
    income  = user["profile"]["monthly_income"]
    sex     = user["profile"]["sex"]
    summary = sorted(user["monthly_summary"], key=lambda x: x["amount"], reverse=True)
    total   = sum(s["amount"] for s in summary)

    # 소비 패턴 텍스트
    spending_text = "\n".join([
        f"  - {s['category']}: {s['amount']:,}원 ({s['ratio']:.0f}%)"
        for s in summary
    ])

    # 추천 결과 텍스트
    def fmt_items(items: list, type_label: str) -> str:
        if not items:
            return f"{type_label}: 추천 없음"
        lines = [f"{type_label}:"]
        for i, item in enumerate(items, 1):
            lines.append(f"  [{i}] {item['name']}")
            # 정책은 core_benefit, 카드/보험은 top_benefit
            benefit = item.get("core_benefit") or item.get("top_benefit", "")
            lines.append(f"      핵심혜택: {benefit}")
            if type_label == "정책":
                lines.append(f"      조건: {item.get('condition','')}")
            lines.append(f"      추천사유: {item['reason'][:80]}")
        return "\n".join(lines)

    prompt = f"""당신은 청년 금융 추천 시스템의 공정한 평가자입니다.
아래 유저 정보와 추천 결과를 보고 각 추천이 얼마나 적합한지 평가해주세요.

## 유저 정보
- 나이: {age}세 / 성별: {sex}
- 월 소득: {income:,}원
- 이번 달 총 지출: {total:,}원

## 이번 달 소비 패턴
{spending_text}

## 추천 결과
{fmt_items(results['cards'], '카드')}

{fmt_items(results['insurances'], '보험')}

{fmt_items(results['policies'], '정책')}

## 평가 기준
각 추천 항목에 대해 다음 기준으로 1~5점 평가:
- 5점: 유저 소비 패턴과 완벽히 일치, 매우 적합
- 4점: 유저 소비 패턴과 잘 맞음, 적합
- 3점: 보통, 일부 맞지만 더 좋은 선택지 있을 수 있음
- 2점: 유저 패턴과 맞지 않는 부분 있음
- 1점: 유저와 전혀 맞지 않음

## 응답 형식 (JSON만 출력, 다른 텍스트 없이)
{{
  "cards": [
    {{"name": "상품명", "score": 점수(1-5), "reason": "평가 이유 1문장"}}
  ],
  "insurances": [
    {{"name": "상품명", "score": 점수(1-5), "reason": "평가 이유 1문장"}}
  ],
  "policies": [
    {{"name": "상품명", "score": 점수(1-5), "reason": "평가 이유 1문장"}}
  ],
  "overall_score": 전체평균점수(소수점1자리),
  "overall_comment": "전체 추천에 대한 총평 1~2문장"
}}"""

    try:
        response = client.messages.create(
            model      = "claude-haiku-4-5-20251001",
            max_tokens = 1000,
            messages   = [{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # JSON 파싱
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except Exception:
                    continue
        return json.loads(text)

    except Exception as e:
        print(f"    ⚠️  LLM Judge 실패: {e}")
        return {"error": str(e), "overall_score": 0}


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
# 메인
# =============================================
def main():
    print("="*62)
    print("🧑‍⚖️  추천 시스템 LLM-as-Judge 평가")
    print(f"   서버: {BASE_URL}")
    print(f"   모델: claude-haiku-4-5-20251001")
    print(f"   유저: {len(TEST_USERS)}명")
    print(f"   시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*62)

    conn = get_db()

    print("\n[1] 유저 세팅")
    setup_users(conn)
    print("  ✅ 완료")

    print(f"\n[2] API 순차 호출 (유저당 {CALL_INTERVAL}초 간격)")
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

    print("\n[3] LLM Judge 평가")
    all_scores   = []
    per_user_out = {}

    for user in TEST_USERS:
        if user["name"] in failed:
            continue

        results = fetch_results(user["user_id"], conn)
        total_rec = (len(results["cards"]) + len(results["insurances"])
                     + len(results["policies"]))

        if total_rec == 0:
            print(f"\n  [{user['name']}] 추천 결과 없음 - skip")
            continue

        print(f"\n  [{user['name']}] 평가 중...", flush=True)
        judgment = llm_judge(user, results)

        overall = judgment.get("overall_score", 0)
        comment = judgment.get("overall_comment", "")
        all_scores.append(overall)

        # 출력
        age    = datetime.now().year - user["profile"]["birth"].year
        income = user["profile"]["monthly_income"]
        print(f"    나이: {age}세 / 소득: {income:,}원")

        for pk, label in [("cards","카드"), ("insurances","보험"), ("policies","정책")]:
            items = judgment.get(pk, [])
            for item in items:
                score = item.get("score", "-")
                name  = item.get("name", "")
                reason = item.get("reason", "")
                star  = "⭐" * int(score) if isinstance(score, (int,float)) else ""
                print(f"    [{label}] {name}")
                print(f"      점수: {score}/5 {star}")
                print(f"      평가: {reason}")

        print(f"    ─ 전체 점수: {overall}/5")
        print(f"    ─ 총평: {comment}")

        per_user_out[user["user_id"]] = {
            "name":           user["name"],
            "overall_score":  overall,
            "overall_comment": comment,
            "details":        judgment,
        }

    # ── 전체 요약 ──
    if all_scores:
        avg_score = round(sum(all_scores) / len(all_scores), 2)
        print("\n" + "="*62)
        print(f"📊 LLM Judge 전체 결과 ({len(all_scores)}명)")
        print("="*62)
        print(f"  평균 점수: {avg_score}/5.0")
        print(f"  점수 분포: {[s for s in all_scores]}")

        # 점수별 해석
        if avg_score >= 4.0:
            grade = "우수 (추천이 유저 맥락과 잘 맞음)"
        elif avg_score >= 3.0:
            grade = "보통 (개선 여지 있음)"
        else:
            grade = "미흡 (추천 품질 개선 필요)"
        print(f"  평가: {grade}")
        print("="*62)

        if failed:
            print(f"\n  ⚠️  실패: {', '.join(failed)}")

        output = {
            "timestamp":   datetime.now().isoformat(),
            "model":       "claude-haiku-4-5-20251001",
            "eval_count":  len(all_scores),
            "avg_score":   avg_score,
            "all_scores":  all_scores,
            "failed":      failed,
            "per_user":    per_user_out,
        }
        with open("eval_llm_result.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"\n✅ 결과 저장: eval_llm_result.json")

    conn.close()
    print(f"   종료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()