"""
Jaccard Similarity 기반 추천 평가 모듈
- 동의어 정규화: 상품 혜택 키워드를 유저 카테고리 키워드 공간으로 통일
- 금융 도메인 불용어 제거: "할인", "지원" 등 의미 없는 공통 단어 제거
- 실제 API 호출 기반 eval.py에서 import해서 사용

from jaccard_similarity import calc_jaccard_scores
"""
import json
import re

# =============================================
# 금융 도메인 불용어 (교집합 부풀림 방지)
# =============================================
STOPWORDS = {
    "할인", "지원", "혜택", "제공", "서비스", "특화", "맞춤",
    "청년", "전용", "전국", "기본", "추가", "최대", "최소",
    "카드", "보험", "정책", "상품", "이용", "신청", "가입",
    "월", "연", "최대", "이하", "이상", "기준", "조건",
    "지급", "적용", "해당", "가능", "제외", "포함",
    "생활비", "생활", "일반", "기타", "기본형", "표준형",
}

# =============================================
# 상품 키워드 → 유저 카테고리 키워드 동의어 정규화
# 상품 혜택에 나오는 단어를 유저 키워드 공간으로 매핑
# =============================================
PRODUCT_SYNONYM_MAP = {
    # 교통
    "버스": "대중교통", "지하철": "대중교통", "전철": "대중교통",
    "전기차": "대중교통", "킥보드": "대중교통", "따릉이": "대중교통",
    "티머니": "교통카드", "환승": "교통",
    # 식비
    "외식": "음식점", "음식점할인": "음식점", "식당": "음식점",
    "배달의민족": "배달앱", "요기요": "배달앱", "쿠팡이츠": "배달앱",
    "편의점할인": "편의점", "CU": "편의점", "GS25": "편의점",
    "세븐일레븐": "편의점", "이마트24": "편의점",
    "마트할인": "마트", "이마트": "마트", "홈플러스": "마트",
    "롯데마트": "마트", "코스트코": "마트",
    # 카페
    "스타벅스할인": "카페", "이디야": "카페", "투썸플레이스": "카페",
    "메가커피": "카페", "컴포즈": "카페",
    # 쇼핑
    "온라인몰": "온라인쇼핑", "G마켓": "쇼핑", "옥션": "쇼핑",
    "11번가": "쇼핑", "위메프": "쇼핑", "티몬": "쇼핑",
    "SSG": "쇼핑", "롯데온": "쇼핑", "무신사": "쇼핑",
    "올리브영": "쇼핑", "다이소": "쇼핑",
    # 주거
    "월세지원": "월세", "전세지원": "전세", "임대주택": "임대",
    "주거비지원": "주거비", "공과금지원": "공과금",
    # 의료
    "병원비": "의료비", "진료비": "의료비", "수술비": "수술",
    "입원비": "입원", "통원비": "통원", "처방약": "처방",
    "약제비지원": "약제비", "검진비": "건강검진",
    "한의": "한의원", "치과치료": "치과",
    # 여행
    "항공권": "항공", "항공마일리지": "마일리지",
    "호텔할인": "호텔", "숙박비": "숙박",
    "공항라운지": "라운지", "해외수수료": "해외결제",
    "환전우대": "환전", "여행보험": "여행",
    # 자동차
    "주유할인": "주유", "리터당할인": "주유", "주유소": "주유소",
    "세차비": "세차", "정비소": "카센터", "주차비": "주차",
    "자동차보험료": "자동차보험", "운전자보험": "운전자",
    "블랙박스할인": "블랙박스",
    # 문화
    "영화할인": "영화", "공연티켓": "공연", "전시관": "전시",
    "OTT구독": "OTT", "스트리밍": "OTT",
    "도서구매": "도서", "교보문고": "도서", "YES24": "도서",
    "게임아이템": "게임", "PC방": "게임",
    # 교육
    "학원비": "학원", "강의비": "강의", "응시료": "자격증",
    "자격증취득": "자격증", "어학시험": "토익",
    "훈련비": "훈련", "수강료": "학원",
    # 사업
    "창업자금": "창업", "사업화자금": "사업화",
    "소상공인지원": "소상공인", "창업지원금": "지원금",
    # 투자/금융
    "적금이율": "적금", "이자우대": "이자",
    "세액공제혜택": "세액공제", "연금저축": "연금",
    "자산형성지원": "자산형성",
    # 주유
    "SK에너지": "주유소", "GS칼텍스": "주유소",
    "현대오일뱅크": "주유소", "S-OIL": "주유소",
    # 통신
    "통신요금": "통신비", "데이터요금": "통신비",
    "SKT": "통신", "KT": "통신", "LG유플러스": "통신",
    # 운동/건강
    "헬스장": "헬스", "피트니스센터": "피트니스",
    "수영장": "수영", "스포츠용품": "스포츠",
    "요가원": "요가", "필라테스원": "필라테스",
}

# =============================================
# 유저 카테고리 → 혜택 키워드 동의어 맵
# =============================================
USER_CATEGORY_KEYWORDS = {
    "식비": {
        "외식", "음식점", "식당", "배달앱", "배달", "배민", "쿠팡이츠",
        "식비", "음식", "밥", "편의점", "마트", "슈퍼", "식품",
        "맥도날드", "버거킹", "패스트푸드",
    },
    "교통": {
        "교통", "대중교통", "버스", "지하철", "전철", "KTX",
        "택시", "교통카드", "환승", "교통비",
    },
    "카페": {
        "카페", "커피", "스타벅스", "이디야", "투썸",
        "음료", "라떼", "아메리카노", "베이커리",
    },
    "쇼핑": {
        "쇼핑", "온라인쇼핑", "쿠팡", "네이버쇼핑",
        "백화점", "아울렛", "의류", "패션",
    },
    "주거": {
        "주거", "월세", "전세", "임대", "주택", "아파트",
        "관리비", "주거비", "공과금", "전기", "가스", "난방",
    },
    "의료": {
        "의료", "병원", "한의원", "치과", "약국", "약제비",
        "건강", "진료", "입원", "통원", "수술", "치료",
        "건강검진", "처방", "의료비",
    },
    "여행": {
        "여행", "해외", "항공", "공항", "라운지", "호텔",
        "숙박", "관광", "환전", "해외결제", "마일리지",
    },
    "자동차": {
        "자동차", "차량", "주유", "기름", "휘발유",
        "주차", "카센터", "정비", "세차", "운전자", "블랙박스",
    },
    "문화": {
        "문화", "영화", "공연", "전시", "뮤지컬",
        "OTT", "넷플릭스", "도서", "독서", "게임", "문화예술",
    },
    "교육": {
        "교육", "학원", "자격증", "토익", "어학",
        "훈련", "내일배움카드", "장학금", "등록금",
    },
    "사업": {
        "창업", "사업", "비즈니스", "소상공인",
        "사업화", "스타트업", "지원금", "운영비",
    },
    "투자": {
        "투자", "자산", "저축", "적금", "펀드", "연금",
        "재테크", "자산형성", "이자", "세액공제",
    },
    "주유": {
        "주유", "기름", "휘발유", "경유", "주유소",
    },
    "통신": {
        "통신", "휴대폰", "SKT", "KT", "LG유플러스",
        "요금제", "데이터", "통신비",
    },
    "운동": {
        "운동", "헬스", "피트니스", "스포츠", "수영",
        "요가", "필라테스", "골프", "건강관리",
    },
    "여가": {
        "여가", "레저", "취미", "캠핑", "등산",
    },
}


# =============================================
# 텍스트 → 정규화된 키워드 집합
# =============================================
def _tokenize(text: str) -> set:
    if not text:
        return set()
    text = re.sub(r"\d+\.?\d*%", "", text)
    text = re.sub(r"\d+", "", text)
    text = re.sub(r"[·•/\-_\[\]{}()\",']", " ", text)
    tokens = set()
    for t in text.split():
        t = t.strip()
        if len(t) >= 2 and not re.match(r"^[원만억천%,\.\s]+$", t):
            tokens.add(t)
    return tokens


def _normalize_keywords(keywords: set) -> set:
    """동의어 정규화 + 불용어 제거."""
    normalized = set()
    for kw in keywords:
        # 동의어 맵 적용
        mapped = PRODUCT_SYNONYM_MAP.get(kw, kw)
        # 불용어 제거
        if mapped not in STOPWORDS:
            normalized.add(mapped)
    return normalized


def _parse_benefits(raw: str) -> set:
    kws = set()
    if not raw:
        return kws
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            for k, v in parsed.items():
                kws.update(_tokenize(k))
                kws.update(_tokenize(str(v)))
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    kws.update(_tokenize(item.get("label", "")))
                    kws.update(_tokenize(item.get("value", "")))
    except Exception:
        kws.update(_tokenize(raw))
    return _normalize_keywords(kws)


def _parse_tags(raw: str) -> set:
    kws = set()
    if not raw:
        return kws
    try:
        tags = json.loads(raw)
        if isinstance(tags, list):
            for t in tags:
                kws.update(_tokenize(str(t)))
    except Exception:
        kws.update(_tokenize(raw))
    return _normalize_keywords(kws)


# =============================================
# 상품별 키워드 추출
# =============================================
def extract_card_keywords(card: dict) -> set:
    kws = set()
    kws.update(_normalize_keywords(_tokenize(card.get("top_benefit", "") or "")))
    kws.update(_parse_benefits(card.get("benefits", "") or ""))
    return kws

def extract_insurance_keywords(ins: dict) -> set:
    kws = set()
    kws.update(_normalize_keywords(_tokenize(ins.get("top_benefit", "") or "")))
    kws.update(_normalize_keywords(_tokenize(ins.get("name", "") or ins.get("insurance_name", "") or "")))
    kws.update(_parse_benefits(ins.get("benefits", "") or ""))
    return kws

def extract_policy_keywords(policy: dict) -> set:
    kws = set()
    kws.update(_normalize_keywords(_tokenize(policy.get("core_benefit", "") or "")))
    kws.update(_normalize_keywords(_tokenize(policy.get("category", "") or "")))
    kws.update(_normalize_keywords(_tokenize(policy.get("name", "") or policy.get("policy_name", "") or "")))
    kws.update(_parse_tags(policy.get("tags", "") or ""))
    return kws


# =============================================
# 유저 키워드 집합 생성
# =============================================
def get_user_keywords(user: dict) -> set:
    summary  = sorted(user["monthly_summary"], key=lambda x: x["amount"], reverse=True)
    total    = sum(s["amount"] for s in summary)
    keywords = set()

    for s in summary:
        cat   = s["category"]
        ratio = s["amount"] / total if total > 0 else 0
        cat_kws = USER_CATEGORY_KEYWORDS.get(cat, {cat})

        if ratio >= 0.30:
            keywords.update(cat_kws)
        elif ratio >= 0.15:
            kw_list = sorted(cat_kws)
            keywords.update(kw_list[:max(1, len(kw_list)//2)])
        else:
            keywords.add(cat)

    # 유저 키워드도 불용어 제거
    return keywords - STOPWORDS


# =============================================
# Overlap Coefficient
# 분모를 합집합이 아닌 더 작은 집합으로 나눔
# → 상품 키워드가 적어도 매칭률 공정하게 측정
# Jaccard와 달리 유저 키워드 수에 덜 민감함
# =============================================
def overlap_coefficient(a: set, b: set) -> float:
    """Overlap Coefficient = 교집합 / min(|A|, |B|)"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return round(inter / min(len(a), len(b)), 4)


def calc_jaccard_scores(user: dict, results: dict) -> dict:
    """유저 vs 추천 상품 Overlap Coefficient 계산."""
    user_kws = get_user_keywords(user)
    scores   = {}

    for pk, extract_fn in [
        ("cards",      extract_card_keywords),
        ("insurances", extract_insurance_keywords),
        ("policies",   extract_policy_keywords),
    ]:
        sims = []
        for item in results[pk]:
            item_kws = extract_fn(item)
            sim      = overlap_coefficient(user_kws, item_kws)
            matched  = sorted(user_kws & item_kws)
            sims.append({
                "name":    item.get("name", ""),
                "score":   sim,
                "matched": matched,
            })

        avg = round(sum(s["score"] for s in sims) / len(sims), 4) if sims else 0.0
        scores[pk] = {"avg": avg, "count": len(sims), "items": sims}

    all_avgs = [scores[pk]["avg"] for pk in ["cards","insurances","policies"]
                if scores[pk]["avg"] > 0]
    scores["overall_avg"] = round(sum(all_avgs)/len(all_avgs), 4) if all_avgs else 0.0
    return scores


# =============================================
# 테스트
# =============================================
if __name__ == "__main__":
    user = {
        "name": "식비_교통_중심",
        "monthly_summary": [
            {"category": "식비",  "amount": 200000, "ratio": 45.0},
            {"category": "교통",  "amount": 120000, "ratio": 27.0},
            {"category": "카페",  "amount": 60000,  "ratio": 13.5},
            {"category": "쇼핑",  "amount": 40000,  "ratio": 9.0},
            {"category": "기타",  "amount": 24000,  "ratio": 5.5},
        ]
    }

    user_kws = get_user_keywords(user)
    print(f"유저 키워드 ({len(user_kws)}개): {sorted(user_kws)[:15]}...")

    # 실제 DB 포맷 테스트
    tests = [
        {
            "name": "NH 청년 내일 카드",
            "top_benefit": "청년 전용 생활비 지원",
            "benefits": '[{"label": "교통", "value": "대중교통 30% 할인"}, {"label": "편의점", "value": "편의점 5% 할인"}, {"label": "통신", "value": "통신비 월 지원"}]'
        },
        {
            "name": "하나카드 트래블로그",
            "top_benefit": "해외여행 특화",
            "benefits": '[{"label": "해외", "value": "해외 결제 수수료 면제"}, {"label": "환전", "value": "환전 우대"}, {"label": "공항", "value": "인천공항 주차 할인"}]'
        },
        {
            "name": "삼성 taptap O",
            "top_benefit": "외식/카페 최대 10% 할인",
            "benefits": '[{"label": "외식", "value": "음식점 10% 할인"}, {"label": "카페", "value": "스타벅스 5% 할인"}, {"label": "편의점", "value": "CU/GS25 5% 할인"}]'
        },
    ]

    for card in tests:
        card_kws = extract_card_keywords(card)
        sim = jaccard_similarity(user_kws, card_kws)
        matched = sorted(user_kws & card_kws)
        print(f"\n[{card['name']}]")
        print(f"  상품 키워드: {sorted(card_kws)}")
        print(f"  Jaccard: {sim:.4f}  매칭: {matched}")