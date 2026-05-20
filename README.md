프로젝트 파일들 참고해서 작성해줄게.

---

# AI Service (청년 맞춤형 금융 생활 관리 플랫폼)

## 📌 개요 (Executive Summary)

수집된 사용자 소비 데이터를 분석하여 월별 리포트, 또래 비교, 맞춤형 금융 상품 및 청년 정책 추천을 제공하는 AI 특화 마이크로서비스입니다.

딱딱한 숫자 나열을 넘어 AI가 분석한 소비 패턴을 친근한 자연어로 전달하고, 사용자 조건에 맞는 혜택 정보를 자동으로 큐레이션하여 청년 세대의 능동적인 금융 생활을 지원합니다.

### 핵심 가치 (Core Values)

- **AI 월별 소비 리포트**: 카테고리별 지출 비율, 전월 대비 증감, 낭비성 지출 경고를 포함한 자연어 리포트 자동 생성
- **또래 비교 분석**: 유사한 연령대·소득 수준 그룹의 평균 소비 데이터와 비교한 긍정적 응원 메시지 제공
- **비식별화 파이프라인**: 민감한 금융 데이터를 LLM 호출 전 마스킹·익명화 처리하여 개인정보 보호
- **비동기 리포트 생성**: LLM 호출을 비동기로 처리하고 완료 시 푸시 알림 발송

---

## 🛠️ 기술 스택 (Technology Stack)

### Backend Core

- **Language**: Python 3.9
- **Framework**: FastAPI 0.115.0
- **ASGI Server**: Uvicorn 0.30.0

### Infrastructure & Databases

- **Main DB**: PostgreSQL 16 (AI 인사이트, 추천 결과 저장)
- **ORM**: SQLAlchemy 2.0.36
- **Message Broker**: NATS JetStream (비동기 이벤트 구동 처리)
- **LLM API**: Anthropic Claude API (anthropic 0.34.0)
- **HTTP Client**: httpx 0.27.0 (내부 서비스 간 통신)

### Architecture & Patterns

- **Layered Architecture**: MVC 계층 분리 (router → service → repository). Entity의 프리젠테이션 계층 노출 금지
- **Communication**: 동기 호출 시 httpx + 서킷 브레이커 패턴 적용. 비동기 이벤트 통신에는 NATS JetStream 활용
- **Standard Responses**: 모든 API 응답은 `CommonResponse[T]` Pydantic 모델로 일관되게 래핑
- **Data Transfer Objects**: Pydantic BaseModel을 활용한 요청/응답 스키마 분리
- **비식별화**: LLM 호출 전 userId SHA-256 해싱, 가맹점명 카테고리 대체, 금액 반올림 처리

---

## 📡 API 명세 요약 (AI API Endpoints)

| Domain | Method | Endpoint | Description |
|--------|--------|----------|-------------|
| Report | GET | /api/ai/report/monthly | AI 월간 소비 리포트 조회 |
| Report | POST | /api/ai/report/monthly | AI 월간 소비 리포트 생성 요청 |
| Report | GET | /api/ai/report/weekly-expense | 주간 지출 데이터 조회 |
| Report | GET | /api/ai/report/peers-comparison | 또래 비교 데이터 조회 |
| Insight | GET | /api/ai/insights | AI 인사이트 목록 조회 |
| Internal | POST | /api/internal/report/generate | 리포트 생성 요청 (내부 서비스 전용) |

---

## 📖 Reference Documentation

- [FastAPI 공식 문서](https://fastapi.tiangolo.com)
- [SQLAlchemy 2.0 공식 문서](https://docs.sqlalchemy.org/en/20/)
- [Anthropic Claude API 문서](https://docs.anthropic.com)
- [NATS Python Client 문서](https://github.com/nats-io/nats.py)
- [Pydantic v2 공식 문서](https://docs.pydantic.dev/latest/)

---

---

# Recommend Service (청년 맞춤형 금융 생활 관리 플랫폼)

## 📌 개요 (Executive Summary)

사용자의 소비 패턴과 온보딩 정보를 분석하여 최적의 카드·보험 상품과 청년 정책을 추천하는 추천 특화 마이크로서비스입니다.

파편화된 청년 금융·복지 정보를 한곳에서 접할 수 있도록 공공데이터 포털 API, 금융감독원 API, 보험다모아 크롤링 데이터를 통합하여 사용자 조건에 맞는 정보를 자동으로 큐레이션합니다.

### 핵심 가치 (Core Values)

- **소비 패턴 기반 카드 추천**: 최근 3개월 소비 카테고리 TOP3 분석으로 최적 혜택 카드 제안
- **라이프스타일 맞춤 보험 추천**: 인구통계 정보와 특수 소비 내역(반려용품 → 펫보험 등) 트리거 매칭
- **청년 정책 AI 추천**: 온보딩 정보 기반 조건 필터링 + Graph RAG 구조로 정책 간 충돌·연계 관계 탐색
- **북마크 및 알림**: 관심 정책·상품 북마크 시 마감 D-7, D-1 알림 자동 예약

---

## 🛠️ 기술 스택 (Technology Stack)

### Backend Core

- **Language**: Java 17 (LTS)
- **Framework**: Spring Boot 3.5.14
- **Build Tool**: Gradle (Gradle Wrapper)

### Infrastructure & Databases

- **Main DB**: PostgreSQL 16 (추천 결과, 북마크, 청년정책 데이터 저장)
- **Cache**: Redis 7.x (추천 결과 캐싱, Rate Limiting)
- **Message Broker**: NATS JetStream (비동기 이벤트 구동 처리)
- **Search Engine**: Elasticsearch (정책 키워드 전문 검색)
- **Container & Orchestration**: Docker, Kubernetes (Amazon EKS)
- **CI/CD**: GitLab CI/CD, Jenkins, AWS ECR

### Architecture & Patterns

- **Layered Architecture**: 철저한 MVC 계층 분리 (Controller → Service → Repository). `@Entity`의 프리젠테이션 계층 노출 금지
- **Rule-based Matching Engine**: 소비 TOP3 카테고리 가중 점수 매칭으로 카드 추천, 특수 소비 키워드 트리거로 보험 추천
- **Graph RAG**: NetworkX 기반 정책 간 충돌·연계 관계 그래프 탐색으로 중복 신청 방지 및 연계 신청 팁 제공
- **Communication**: 동기 호출 시 Spring Cloud OpenFeign + Resilience4j 서킷 브레이커 적용. 비동기 이벤트 통신에는 NATS JetStream 활용
- **Standard Responses**: 모든 API 응답은 `CommonResponse<T>` 레코드로 일관되게 래핑

---

## 📡 API 명세 요약 (Recommend API Endpoints)

| Domain | Method | Endpoint | Description |
|--------|--------|----------|-------------|
| Policy | GET | /api/recommend/policies | 청년 정책 추천 목록 조회 |
| Policy | GET | /api/v1/recommend/policies/{policyId} | 청년 정책 상세 조회 |
| Policy | GET | /api/recommend/policies/bookmarks | 북마크한 정책 목록 조회 |
| Insurance | GET | /api/recommend/insurances | 추천 보험 목록 조회 |
| Card | GET | /api/recommend/cards/{recommendId} | 카드 추천 상세 조회 |
| Bookmark | PATCH | /api/recommend/bookmark/patch | 북마크 설정/해제 |
| Alarm | PATCH | /api/recommend/alarm/patch | 알림 설정/해제 |

---

## 📖 Reference Documentation

- [Spring Boot 공식 문서](https://docs.spring.io/spring-boot/docs/3.5.14/reference/html/)
- [Spring Data JPA 공식 문서](https://docs.spring.io/spring-data/jpa/docs/current/reference/html/)
- [Resilience4j 공식 문서](https://resilience4j.readme.io/docs)
- [OpenFeign 공식 문서](https://docs.spring.io/spring-cloud-openfeign/docs/current/reference/html/)
- [공공데이터포털 API](https://www.data.go.kr)
- [금융감독원 통합비교공시 API](https://finlife.fss.or.kr)