# AI & Recommend Service (청년 맞춤형 금융 생활 관리 플랫폼)

## 📌 개요 (Executive Summary)

수집된 사용자 소비 데이터를 분석하여 월별 리포트, 또래 비교, 맞춤형 금융 상품 및 청년 정책 추천을 제공하는 AI·추천 특화 마이크로서비스입니다.

딱딱한 숫자 나열을 넘어 AI가 분석한 소비 패턴을 친근한 자연어로 전달하고, 사용자 조건에 맞는 혜택 정보를 자동으로 큐레이션하여 청년 세대의 능동적인 금융 생활을 지원합니다.

### 핵심 가치 (Core Values)

- **AI 월별 소비 리포트**: 카테고리별 지출 비율, 전월 대비 증감, 낭비성 지출 경고를 포함한 자연어 리포트 자동 생성
- **또래 비교 분석**: 유사한 연령대·소득 수준 그룹의 평균 소비 데이터와 비교한 긍정적 응원 메시지 제공
- **소비 패턴 기반 카드 추천**: 최근 3개월 소비 카테고리 TOP3 분석으로 최적 혜택 카드 제안
- **라이프스타일 맞춤 보험 추천**: 인구통계 정보와 특수 소비 내역(반려용품 → 펫보험 등) 트리거 매칭
- **청년 정책 AI 추천**: 온보딩 정보 기반 조건 필터링 + Qdrant 벡터 검색으로 사용자 조건에 맞는 정책 큐레이션
- **북마크 및 알림**: 관심 정책·상품 북마크 시 마감 D-7, D-1 알림 자동 예약
- **비식별화 파이프라인**: 민감한 금융 데이터를 LLM 호출 전 마스킹·익명화 처리하여 개인정보 보호
- **비동기 리포트 생성**: LLM 호출을 비동기로 처리하고 완료 시 푸시 알림 발송

---

## 🛠️ 기술 스택 (Technology Stack)

### Backend Core

| 항목 | 내용 |
|------|------|
| Language | Python 3.9.23 |
| Framework | FastAPI 0.115.0 |
| ASGI Server | Uvicorn 0.30.0 |

### Infrastructure & Databases

| 항목 | 내용 |
|------|------|
| Main DB | PostgreSQL 16 (AI 인사이트, 추천 결과, 북마크 저장) |
| ORM | SQLAlchemy 2.0.36 |
| Vector DB | Qdrant (청년 정책 벡터 임베딩 저장 및 유사도 검색) |
| Message Broker | NATS JetStream (비동기 이벤트 구동 처리) |
| LLM API | Anthropic Claude API (anthropic 0.34.0) |
| HTTP Client | httpx 0.27.0 (내부 서비스 간 통신) |

### Architecture & Patterns

- **Layered Architecture**: MVC 계층 분리 (router → service → repository). Entity의 프리젠테이션 계층 노출 금지
- **Standard Responses**: 모든 API 응답은 `CommonResponse[T]` Pydantic 모델로 일관되게 래핑
- **Data Transfer Objects**: Pydantic BaseModel을 활용한 요청/응답 스키마 분리
- **TSID**: 직접 구현한 TSID 생성기로 PK 관리 (`app/core/utils/tsid.py`), Java 서비스와 포맷 통일
- **비식별화**: LLM 호출 전 userId SHA-256 해싱, 가맹점명 카테고리 대체, 금액 반올림 처리
- **벡터 검색**: 청년 정책 데이터를 Qdrant에 임베딩하여 사용자 조건 기반 유사도 검색
- **Communication**: 동기 호출 시 httpx + 서킷 브레이커 패턴 적용. 비동기 이벤트 통신에는 NATS JetStream 활용

---

## 📁 프로젝트 구조 (Project Structure)

```text
app/
├── core/
│   ├── config/
│   │   └── database.py         # PostgreSQL 엔진, Base, get_db
│   ├── error/
│   │   ├── exception.py        # BusinessException
│   │   └── handler.py          # 전역 예외 핸들러
│   ├── common/
│   │   └── response.py         # CommonResponse[T]
│   └── utils/
│       └── tsid.py             # TSID 생성기
├── domain/
│   ├── report/
│   │   ├── entity.py           # AiReport
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   └── schema.py           # Pydantic DTO
│   ├── insight/
│   │   ├── entity.py           # AiInsight
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   └── schema.py
│   └── recommend/
│       ├── entity.py           # RecommendCard, RecommendInsurance, RecommendPolicy, Bookmark
│       ├── router.py
│       ├── service.py
│       ├── repository.py
│       └── schema.py
└── main.py
```

---

## 📡 API 명세 요약 (API Endpoints)

### AI Report

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/ai/report/monthly | AI 월간 소비 리포트 조회 |
| POST | /api/ai/report/monthly | AI 월간 소비 리포트 생성 요청 |
| GET | /api/ai/report/weekly-expense | 주간 지출 데이터 조회 |
| GET | /api/ai/report/peers-comparison | 또래 비교 데이터 조회 |

### Insight

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/ai/insights | AI 인사이트 목록 조회 |

### Internal

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/internal/report/generate | 리포트 생성 요청 (내부 서비스 전용, 외부 노출 금지) |

### Recommend

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/recommend/policies | 청년 정책 추천 목록 조회 |
| GET | /api/recommend/policies/{policyId} | 청년 정책 상세 조회 |
| GET | /api/recommend/policies/bookmarks | 북마크한 정책 목록 조회 |
| GET | /api/recommend/insurances | 추천 보험 목록 조회 |
| GET | /api/recommend/cards/{recommendId} | 카드 추천 상세 조회 |
| PATCH | /api/recommend/bookmark/patch | 북마크 설정/해제 |
| PATCH | /api/recommend/alarm/patch | 알림 설정/해제 |

---

## 🗄️ 데이터베이스 구조 (Database Schema)

### PostgreSQL 테이블

| 테이블 | 설명 |
|--------|------|
| ai_report | AI 월간 소비 리포트 저장 |
| ai_insight | AI 분석 인사이트 (카드/보험/정책 추천, 월별 분석 등) |
| recommend_card | AI 카드 추천 결과 |
| recommend_insurance | AI 보험 추천 결과 |
| recommend_policy | AI 청년 정책 추천 결과 |
| bookmark | 정책·보험·카드 북마크 통합 관리 |

### Qdrant 컬렉션

| 컬렉션 | 설명 |
|--------|------|
| youth_policy | 청년 정책 텍스트 임베딩 (정책명, 지원내용, 대상 조건 등) |


---

## 📖 Reference Documentation

- [FastAPI 공식 문서](https://fastapi.tiangolo.com)
- [SQLAlchemy 2.0 공식 문서](https://docs.sqlalchemy.org/en/20/)
- [Qdrant 공식 문서](https://qdrant.tech/documentation/)
- [Anthropic Claude API 문서](https://docs.anthropic.com)
- [NATS Python Client 문서](https://github.com/nats-io/nats.py)
- [Pydantic v2 공식 문서](https://docs.pydantic.dev/latest/)
- [공공데이터포털 API](https://www.data.go.kr)