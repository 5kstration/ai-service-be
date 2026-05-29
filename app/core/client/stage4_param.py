"""
4단계 파라미터 최적화 실험 (A/B/C/D)

A. 유저 임베딩 텍스트 길이 (short/medium/long/extra_long) → 평균 코사인 유사도
B. 임베딩 차원 (256/512/1024) → 차원별 별도 테이블 생성 후 유사도 비교
C. 벡터 후보 수 (10/20/30) → 평균 유사도 + 타입 다양성
D. 리랭커 top_n (5/7/10) → top score + score gap

실행: python app/core/client/stage4_param_eval.py (프로젝트 루트에서)
결과: stage4_param_eval_result.json
"""
import json
import math
import os
import sys
import time
import statistics
import psycopg2
import boto3
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, "/home/server2/ai-service-be")
load_dotenv()

from sentence_transformers import CrossEncoder

REPEAT = 3

# =============================================
# A. 유저 텍스트 버전
# =============================================
USER_TEXTS = {
    "short": (
        "나이 28세 남자. 월급 350만원. "
        "식비 156,000원, 쇼핑 89,000원, 카페 68,000원."
    ),
    "medium": (
        "나이 28세 남자 청년. 월 소득 3,500,000원. "
        "이번 달 지출: 식비 156,000원, 쇼핑 89,000원, 카페 68,000원, 교통 45,000원. "
        "가장 많이 쓰는 카테고리: 식비, 쇼핑, 카페. "
        "절약이 필요한 영역: 식비, 쇼핑."
    ),
    "long": (
        "나이 28세 남자 청년 직장인. 월 소득 3,500,000원. "
        "이번 달 총 지출 421,000원 (소득의 12%). "
        "지출 상세: 식비 156,000원(37%), 쇼핑 89,000원(21%), "
        "카페 68,000원(16%), 교통 45,000원(11%), 기타 63,000원(15%). "
        "가장 많이 쓰는 카테고리: 식비, 쇼핑, 카페. "
        "절약이 필요한 영역: 식비, 쇼핑. "
        "관심 혜택: 할인카드, 청년정책, 주거지원, 금융혜택."
    ),
    "extra_long": (
        "나이 28세 남자 청년 직장인. 월 소득 3,500,000원. "
        "이번 달 총 지출 421,000원 (소득의 12%). "
        "지출 상세: 식비 156,000원(37%), 쇼핑 89,000원(21%), "
        "카페 68,000원(16%), 교통 45,000원(11%), 기타 63,000원(15%). "
        "식비 지출이 또래 평균 대비 18% 높음. "
        "배달앱, 편의점, 카페 이용이 많은 소비 성향. "
        "교통비 지출로 대중교통 주 이용 추정. "
        "온라인 쇼핑 지출 상당함. "
        "절약이 필요한 영역: 식비(배달앱), 쇼핑(온라인). "
        "관심 혜택: 배달앱 할인카드, 간편결제 할인, 청년정책, 주거지원, 금융혜택, 실손보험. "
        "라이프스타일: 직장인, 자취, 대중교통 이용, 배달음식 선호."
    ),
}

BASE_TEXT        = USER_TEXTS["long"]
DIMENSIONS       = [256, 512, 1024]
CANDIDATES_LIST  = [10, 20, 30]
RERANK_TOP_N_LIST = [5, 7, 10]


# =============================================
# Bedrock
# =============================================
bedrock = boto3.client(
    "bedrock-runtime",
    region_name           = os.getenv("AWS_REGION", "ap-northeast-2"),
    aws_access_key_id     = os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY"),
)

def get_embedding(text: str, dimensions: int = None) -> list[float]:
    body = {"inputText": text}
    if dimensions and dimensions != 1024:
        body["dimensions"] = dimensions
    resp = bedrock.invoke_model(
        modelId     = "amazon.titan-embed-text-v2:0",
        contentType = "application/json",
        accept      = "application/json",
        body        = json.dumps(body),
    )
    return json.loads(resp["body"].read())["embedding"]


# =============================================
# DB 연결 (커넥션 매번 새로 생성 - 트랜잭션 오류 방지)
# =============================================
def new_vector_conn():
    return psycopg2.connect(
        host     = os.getenv("VECTOR_DB_HOST"),
        port     = os.getenv("VECTOR_DB_PORT", 5432),
        dbname   = os.getenv("VECTOR_DB_NAME"),
        user     = os.getenv("VECTOR_DB_USER"),
        password = os.getenv("VECTOR_DB_PASSWORD"),
        sslmode  = os.getenv("DB_SSLMODE", "require"),
    )

def new_main_conn():
    return psycopg2.connect(
        host     = os.getenv("DB_HOST"),
        port     = os.getenv("DB_PORT", 5432),
        dbname   = os.getenv("DB_NAME"),
        user     = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        sslmode  = os.getenv("DB_SSLMODE", "require"),
    )


# =============================================
# 벡터 검색
# =============================================
def vector_search(embedding: list[float], limit: int, table: str = "product_embedding") -> list[dict]:
    emb_str = f"[{','.join(map(str, embedding))}]"
    conn = new_vector_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT product_id, product_type, content,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM {table}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (emb_str, emb_str, limit))
        rows = cur.fetchall()
        cur.close()
        return [
            {"product_id": r[0], "type": r[1], "content": r[2], "similarity": float(r[3])}
            for r in rows
        ]
    finally:
        conn.close()

def summarize(rows: list[dict]) -> dict:
    sims = [r["similarity"] for r in rows]
    dist = {t: sum(1 for r in rows if r["type"] == t) for t in ["card","insurance","policy"]}
    return {
        "avg_similarity": round(statistics.mean(sims), 4),
        "top_similarity": round(max(sims), 4),
        "min_similarity": round(min(sims), 4),
        "type_dist":      dist,
    }


# =============================================
# 실험 A. 유저 텍스트 길이별 유사도
# =============================================
def experiment_A() -> dict:
    print("\n" + "="*60)
    print("실험 A. 유저 임베딩 텍스트 길이별 코사인 유사도")
    print("="*60)

    results = {}
    for name, text in USER_TEXTS.items():
        run_avgs, run_tops, run_mins = [], [], []
        for _ in range(REPEAT):
            emb  = get_embedding(text)
            rows = vector_search(emb, limit=20)
            s    = summarize(rows)
            run_avgs.append(s["avg_similarity"])
            run_tops.append(s["top_similarity"])
            run_mins.append(s["min_similarity"])

        avg = statistics.mean(run_avgs)
        top = statistics.mean(run_tops)
        mn  = statistics.mean(run_mins)

        print(f"\n  [{name.upper()}] {len(text)}자")
        print(f"    평균 유사도: {avg:.4f}")
        print(f"    최고 유사도: {top:.4f}")
        print(f"    최저 유사도: {mn:.4f}")

        results[name] = {
            "text_length":    len(text),
            "avg_similarity": round(avg, 4),
            "top_similarity": round(top, 4),
            "min_similarity": round(mn, 4),
        }

    best = max(results.items(), key=lambda x: x[1]["avg_similarity"])
    print(f"\n  📊 A 최적: '{best[0]}' (평균 유사도 {best[1]['avg_similarity']:.4f})")
    return results


# =============================================
# 실험 B. 임베딩 차원별 유사도 (차원별 별도 테이블)
# =============================================
def create_dim_table(dim: int):
    """차원별 테이블 생성 + 상품 임베딩 저장."""
    table = f"product_embedding_{dim}"
    print(f"\n  [{dim}차원] 테이블 생성 중: {table}")

    # 메인 DB에서 상품 텍스트 조회
    main_conn = new_main_conn()
    try:
        cur = main_conn.cursor()
        cur.execute("SELECT key, company, card_name, top_benefit, benefits FROM card_product")
        cards = cur.fetchall()
        cur.execute("SELECT key, insurer, insurance_name, top_benefit, benefits FROM insurance_product")
        insurances = cur.fetchall()
        cur.execute("""
            SELECT key, policy_name, org, category, core_benefit,
                   age_min, age_max, income_condition, tags
            FROM policy_product
        """)
        policies = cur.fetchall()
        cur.close()
    finally:
        main_conn.close()

    # 텍스트 준비
    product_texts = []
    for c in cards:
        text = (f"{c[1]} {c[2]}. 핵심 혜택: {c[3]}. 혜택: {c[4] or ''}. "
                f"식비·배달·카페·쇼핑·교통 지출이 많은 20~30대 청년에게 적합.")
        product_texts.append(("card", c[0], text))
    for i in insurances:
        text = (f"{i[1]} {i[2]}. 핵심 혜택: {i[3]}. 혜택: {i[4] or ''}. "
                f"20~30대 청년 직장인에게 적합.")
        product_texts.append(("insurance", i[0], text))
    for p in policies:
        text = (f"{p[1]}. 주관기관: {p[2]}. 카테고리: {p[3]}. "
                f"핵심 혜택: {p[4]}. 지원 대상: {p[5]}~{p[6]}세. "
                f"소득 조건: {p[7] or ''}. 태그: {p[8] or ''}")
        product_texts.append(("policy", p[0], text))

    # 벡터 DB에 테이블 생성 + 임베딩 저장
    vec_conn = new_vector_conn()
    try:
        cur = vec_conn.cursor()

        # 테이블 생성
        cur.execute(f"DROP TABLE IF EXISTS {table}")
        vec_conn.commit()

        cur.execute(f"""
            CREATE TABLE {table} (
                id           VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                product_id   VARCHAR(26) NOT NULL,
                product_type VARCHAR(20) NOT NULL,
                embedding    vector({dim}),
                content      TEXT,
                created_at   TIMESTAMP NOT NULL DEFAULT now()
            )
        """)
        vec_conn.commit()
        print(f"    테이블 생성 완료")

        # 상품별 임베딩 저장 (각각 커밋)
        saved = 0
        for ptype, pid, text in product_texts:
            try:
                emb = get_embedding(text, dimensions=dim)
                emb_str = f"[{','.join(map(str, emb))}]"
                cur.execute(f"""
                    INSERT INTO {table} (product_id, product_type, embedding, content)
                    VALUES (%s, %s, %s::vector, %s)
                """, (pid, ptype, emb_str, text))
                vec_conn.commit()  # 상품마다 개별 커밋
                saved += 1
            except Exception as e:
                vec_conn.rollback()  # 실패 시 롤백 후 계속
                print(f"      임베딩 실패 - {pid}: {e}")

        print(f"    임베딩 저장 완료: {saved}개")

        # HNSW 인덱스
        cur.execute(f"""
            CREATE INDEX ON {table}
            USING hnsw (embedding vector_cosine_ops)
        """)
        vec_conn.commit()
        print(f"    인덱스 생성 완료")
        cur.close()

    finally:
        vec_conn.close()

    return table


def experiment_B() -> dict:
    print("\n" + "="*60)
    print("실험 B. 임베딩 차원별 코사인 유사도")
    print("="*60)

    tables = {1024: "product_embedding"}  # 1024는 기존 테이블 사용

    # 256, 512 테이블 생성
    for dim in [256, 512]:
        tables[dim] = create_dim_table(dim)

    results = {}
    for dim in DIMENSIONS:
        table     = tables[dim]
        run_avgs  = []
        run_tops  = []
        run_times = []

        for _ in range(REPEAT):
            start = time.time()
            emb   = get_embedding(BASE_TEXT, dimensions=dim if dim != 1024 else None)
            rows  = vector_search(emb, limit=20, table=table)
            elapsed = (time.time() - start) * 1000

            s = summarize(rows)
            run_avgs.append(s["avg_similarity"])
            run_tops.append(s["top_similarity"])
            run_times.append(elapsed)

        avg      = statistics.mean(run_avgs)
        top      = statistics.mean(run_tops)
        avg_time = statistics.mean(run_times)

        print(f"\n  [차원={dim}] 테이블: {table}")
        print(f"    임베딩+검색 시간: {avg_time:.1f}ms")
        print(f"    평균 유사도:      {avg:.4f}")
        print(f"    최고 유사도:      {top:.4f}")

        results[f"dim_{dim}"] = {
            "dimension":      dim,
            "avg_time_ms":    round(avg_time, 1),
            "avg_similarity": round(avg, 4),
            "top_similarity": round(top, 4),
        }

    best = max(results.items(), key=lambda x: x[1]["avg_similarity"])
    print(f"\n  📊 B 최적: {best[1]['dimension']}차원 (평균 유사도 {best[1]['avg_similarity']:.4f})")
    return results


# =============================================
# 실험 C. 벡터 후보 수별 유사도 + 다양성
# =============================================
def experiment_C() -> dict:
    print("\n" + "="*60)
    print("실험 C. 벡터 후보 수별 코사인 유사도 + 다양성")
    print("="*60)

    emb     = get_embedding(BASE_TEXT)
    results = {}

    for n in CANDIDATES_LIST:
        run_stats = []
        run_times = []

        for _ in range(REPEAT):
            start   = time.time()
            rows    = vector_search(emb, limit=n)
            elapsed = (time.time() - start) * 1000
            run_stats.append(summarize(rows))
            run_times.append(elapsed)

        avg_time = statistics.mean(run_times)
        avg_sim  = statistics.mean([s["avg_similarity"] for s in run_stats])
        top_sim  = statistics.mean([s["top_similarity"] for s in run_stats])
        avg_card = statistics.mean([s["type_dist"]["card"]      for s in run_stats])
        avg_ins  = statistics.mean([s["type_dist"]["insurance"] for s in run_stats])
        avg_pol  = statistics.mean([s["type_dist"]["policy"]    for s in run_stats])

        print(f"\n  [CANDIDATES={n}]")
        print(f"    응답시간:    {avg_time:.1f}ms")
        print(f"    평균 유사도: {avg_sim:.4f}")
        print(f"    최고 유사도: {top_sim:.4f}")
        print(f"    타입 분포:   카드 {avg_card:.1f} / 보험 {avg_ins:.1f} / 정책 {avg_pol:.1f}")

        results[f"candidates_{n}"] = {
            "candidates":     n,
            "avg_time_ms":    round(avg_time, 1),
            "avg_similarity": round(avg_sim, 4),
            "top_similarity": round(top_sim, 4),
            "type_dist": {
                "card":      round(avg_card, 1),
                "insurance": round(avg_ins, 1),
                "policy":    round(avg_pol, 1),
            }
        }

    # 종합 점수 (유사도 0.6 + 다양성 0.4)
    print("\n  📊 C 종합 점수 (유사도 0.6 + 다양성 0.4):")
    max_sim = max(v["avg_similarity"] for v in results.values())
    scores  = {}
    for k, v in results.items():
        sim_s = v["avg_similarity"] / max_sim
        total = sum(v["type_dist"].values())
        ratios = [v["type_dist"][t] / total for t in ["card","insurance","policy"]] if total else [0,0,0]
        div_s  = 1 - statistics.stdev(ratios)
        scores[k] = sim_s * 0.6 + div_s * 0.4
        print(f"    CANDIDATES={v['candidates']}: "
              f"유사도={sim_s:.3f}, 다양성={div_s:.3f}, 종합={scores[k]:.3f}")

    best_k = max(scores, key=scores.get)
    best   = results[best_k]
    print(f"\n  🏆 C 최적: CANDIDATES={best['candidates']} (종합점수 {scores[best_k]:.3f})")
    return results


# =============================================
# 실험 D. 리랭커 top_n별 relevance score
# =============================================
def experiment_D() -> dict:
    print("\n" + "="*60)
    print("실험 D. 리랭커 top_n별 relevance score")
    print("="*60)

    print("  모델 로드 중...")
    model = CrossEncoder("bongsoo/klue-cross-encoder-v1")
    model.predict([["warmup", "warmup"]], show_progress_bar=False)
    print("  모델 로드 완료")

    # 후보 30개 고정
    emb  = get_embedding(BASE_TEXT)
    rows = vector_search(emb, limit=30)

    card_texts      = [r["content"] for r in rows if r["type"] == "card"      and r["content"]]
    insurance_texts = [r["content"] for r in rows if r["type"] == "insurance" and r["content"]]
    policy_texts    = [r["content"] for r in rows if r["type"] == "policy"    and r["content"]]

    print(f"  후보: 카드 {len(card_texts)}개 / 보험 {len(insurance_texts)}개 / 정책 {len(policy_texts)}개")

    results = {}
    for top_n in RERANK_TOP_N_LIST:
        run_times      = []
        run_top_scores = []
        run_avg_scores = []
        run_gaps       = []

        for _ in range(REPEAT):
            start      = time.time()
            all_scores = []

            for texts in [card_texts, insurance_texts, policy_texts]:
                if not texts:
                    continue
                pairs    = [[BASE_TEXT, t] for t in texts]
                sc       = model.predict(pairs, show_progress_bar=False)
                sc_f     = sorted(
                    [float(s) for s in np.array(sc).flatten()],
                    reverse=True
                )
                all_scores.extend(sc_f[:min(top_n, len(sc_f))])

            elapsed = (time.time() - start) * 1000

            if all_scores:
                run_times.append(elapsed)
                run_top_scores.append(max(all_scores))
                run_avg_scores.append(statistics.mean(all_scores))
                run_gaps.append(max(all_scores) - min(all_scores))

        if not run_times:
            print(f"\n  [RERANK_TOP_N={top_n}] 결과 없음")
            continue

        avg_time  = statistics.mean(run_times)
        avg_top   = statistics.mean(run_top_scores)
        avg_avg   = statistics.mean(run_avg_scores)
        avg_gap   = statistics.mean(run_gaps)

        print(f"\n  [RERANK_TOP_N={top_n}]")
        print(f"    응답시간:   {avg_time:.1f}ms")
        print(f"    top score:  {avg_top:.4f}")
        print(f"    평균 score: {avg_avg:.4f}")
        print(f"    score gap:  {avg_gap:.4f}  ← 클수록 관련/비관련 구분 명확")

        results[f"top_n_{top_n}"] = {
            "top_n":       top_n,
            "avg_time_ms": round(avg_time, 1),
            "top_score":   round(avg_top,  4),
            "avg_score":   round(avg_avg,  4),
            "score_gap":   round(avg_gap,  4),
        }

    if results:
        max_top = max(v["top_score"] for v in results.values())
        max_gap = max(v["score_gap"] for v in results.values())
        print("\n  📊 D 종합 점수 (top_score 0.5 + gap 0.5):")
        scores = {}
        for k, v in results.items():
            s = (v["top_score"]/max_top)*0.5 + (v["score_gap"]/max_gap)*0.5
            scores[k] = s
            print(f"    top_n={v['top_n']}: top={v['top_score']:.4f}, gap={v['score_gap']:.4f}, 종합={s:.3f}")
        best_k = max(scores, key=scores.get)
        best   = results[best_k]
        print(f"\n  🏆 D 최적: RERANK_TOP_N={best['top_n']} (종합점수 {scores[best_k]:.3f})")

    return results


# =============================================
# 최종 스토리 출력
# =============================================
def print_story(a, b, c, d):
    print("\n" + "="*60)
    print("📖 파라미터 최적화 결과 요약")
    print("="*60)

    best_a = max(a.items(), key=lambda x: x[1]["avg_similarity"])
    print(f"\n[A. 유저 임베딩 텍스트]")
    for name, v in a.items():
        marker = " ← 선택" if name == best_a[0] else ""
        print(f"  {name:12s} ({v['text_length']:3d}자): 평균 유사도 {v['avg_similarity']:.4f}{marker}")

    best_b = max(b.items(), key=lambda x: x[1]["avg_similarity"])
    print(f"\n[B. 임베딩 차원]")
    for k, v in b.items():
        marker = " ← 선택" if k == best_b[0] else ""
        print(f"  {v['dimension']}차원: 유사도 {v['avg_similarity']:.4f}, 시간 {v['avg_time_ms']:.1f}ms{marker}")

    if c:
        max_sim = max(v["avg_similarity"] for v in c.values())
        c_scores = {}
        for k, v in c.items():
            sim_s = v["avg_similarity"] / max_sim
            total = sum(v["type_dist"].values())
            ratios = [v["type_dist"][t] / total for t in ["card","insurance","policy"]] if total else [0,0,0]
            div_s  = 1 - statistics.stdev(ratios)
            c_scores[k] = sim_s * 0.6 + div_s * 0.4
        best_c_k = max(c_scores, key=c_scores.get)
        best_c   = c[best_c_k]
        print(f"\n[C. 벡터 후보 수]")
        for k, v in c.items():
            marker = " ← 선택" if k == best_c_k else ""
            print(f"  CANDIDATES={v['candidates']:2d}: 유사도 {v['avg_similarity']:.4f}, "
                  f"분포 카드{v['type_dist']['card']}/보험{v['type_dist']['insurance']}/정책{v['type_dist']['policy']}{marker}")

    if d:
        max_top  = max(v["top_score"] for v in d.values())
        max_gap  = max(v["score_gap"] for v in d.values())
        d_scores = {k: (v["top_score"]/max_top)*0.5 + (v["score_gap"]/max_gap)*0.5 for k, v in d.items()}
        best_d_k = max(d_scores, key=d_scores.get)
        best_d   = d[best_d_k]
        print(f"\n[D. 리랭커 top_n]")
        for k, v in d.items():
            marker = " ← 선택" if k == best_d_k else ""
            print(f"  top_n={v['top_n']}: top score {v['top_score']:.4f}, gap {v['score_gap']:.4f}{marker}")


# =============================================
# 메인
# =============================================
if __name__ == "__main__":
    print("🚀 4단계 파라미터 최적화 실험 (A/B/C/D)")
    print(f"   시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   반복: {REPEAT}회 평균\n")

    a_results = experiment_A()
    b_results = experiment_B()
    c_results = experiment_C()
    d_results = experiment_D()

    print_story(a_results, b_results, c_results, d_results)

    all_results = {
        "timestamp":      datetime.now().isoformat(),
        "repeat":         REPEAT,
        "A_text_length":  a_results,
        "B_dimension":    b_results,
        "C_candidates":   c_results,
        "D_rerank_top_n": d_results,
    }

    with open("stage4_param_eval_result.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 완료! 결과: stage4_param_eval_result.json")
    print(f"   종료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")