# MoneyLog AI Service

> 청년 맞춤형 금융 생활 관리 플랫폼의 AI·추천 특화 마이크로서비스

수집된 사용자 소비 데이터를 분석하여 월별 리포트, 또래 비교, 맞춤형 금융 상품 및 청년 정책 추천을 제공합니다. <br><br>
보기 힘든 숫자 나열 보단, AI가 소비 패턴을 분석하고 친근한 자연어로 전달하며, 사용자 조건에 맞는 혜택 정보를 자동으로 큐레이션합니다.

---

## 목차

- [기술 스택](#기술-스택)
- [아키텍처](#아키텍처)
- [AI 추천 파이프라인](#ai-추천-파이프라인)
- [프로젝트 구조](#프로젝트-구조)
- [API 명세](#api-명세)
- [CI/CD](#cicd)
- [참고 자료](#참고-자료)

---

## 기술 스택

### Backend Core

| 항목 | 내용 | 선정 이유 |
|------|------|-----------|
| Language | Python 3.9 | AI/ML 생태계 최적, LangGraph·Bedrock SDK 공식 지원 |
| Framework | FastAPI 0.115 | 비동기 처리 + 자동 OpenAPI 문서화, 추천 파이프라인 비동기 실행에 적합 |
| ASGI Server | Uvicorn | FastAPI 공식 권장 ASGI 서버 |

### AI / ML

| 항목 | 내용 | 선정 이유 |
|------|------|-----------|
| LLM Orchestration | LangGraph | 상태 기반 DAG 파이프라인 구성, 노드별 독립 실행 및 에러 핸들링 용이 |
| LLM | AWS Bedrock Claude Haiku | 추천 사유 자연어 생성, ap-northeast-2 리전 지원 |
| Embedding | AWS Bedrock Titan Embed V2 (256차원) | 데이터 복잡성 문제로 1024차원보단 256차원이 성능과 속도면에서 향상 |
| Reranker | bongsoo/klue-cross-encoder-v1 | 한국어 특화 Cross-Encoder, Bi-Encoder 벡터 유사도보다 정교한 관련성 판단 |

### Database

| 항목 | 내용 | 선정 이유 |
|------|------|-----------|
| Main DB | PostgreSQL 16 (AWS RDS) | 추천 결과, 소비 데이터, 목표, 북마크 저장 |
| ORM | SQLAlchemy 2.0 | Python 표준 ORM, 비동기 세션 지원 |
| Vector DB | pgvector (PostgreSQL 확장) | 별도 벡터DB 없이 RDS 내에서 코사인 유사도 검색, 운영 복잡도 최소화 |
| Graph DB | Neo4j AuraDB | 정책 간 충돌(CONFLICTS_WITH), 카테고리 연결(IN_CATEGORY), 유사 상품(SIMILAR_TO) 관계 표현. 벡터 검색으로 감지 불가한 도메인 규칙 인코딩 |
| Cache | Redis Sentinel | 세션 캐시, 고가용성을 위한 Sentinel 구성 |

### Infrastructure

| 항목 | 내용 | 선정 이유 |
|------|------|-----------|
| Container Orchestration | AWS EKS | 프로젝트 표준 인프라, MSA 서비스 통합 관리 |
| Message Broker | AWS SQS | Budget 서비스에서 소비 이벤트 수신, 느슨한 결합 |
| Service Mesh | Istio | 서비스 간 트래픽 관리 및 인증 |
| CI/CD | Jenkins | GitLab 연동, 온프레미스 에이전트 기반 파이프라인 |
| Code Quality | SonarQube | 정적 분석 및 품질 게이트 |
| Tracing | LangSmith | LangGraph 파이프라인 추적 및 디버깅 |
| IaC | Terraform | EKS, VPC, RDS 등 AWS 인프라 코드 관리 |

---

## 아키텍처

```
[프론트엔드 (Next.js)]
        ↓
[API Gateway (Spring)]  →  X-User-Id 헤더 주입
        ↓
[AI Service (FastAPI)]
  ├── SQS Consumer  ←  Budget Service (소비 이벤트)
  ├── SQS Consumer  ←  Auth Service (온보딩 완료)
  ├── LangGraph 추천 파이프라인
  │     ├── pgvector (AWS RDS)
  │     ├── Neo4j AuraDB
  │     └── AWS Bedrock (Claude Haiku, Titan Embed)
  └── Redis Sentinel
```

EKS → 온프레미스 연결은 WireGuard 터널(Bastion EC2 경유)을 통해 이루어집니다.

---

## AI 추천 파이프라인

LangGraph 기반 `profile → embed → vector_search → rerank → filter → graph_expand → conflict → llm → save` 순서로 실행됩니다.

```
┌─────────┐   ┌───────┐   ┌──────────────┐   ┌────────┐
│ Profile │ → │ Embed │ → │ VectorSearch │ → │ Rerank │
└─────────┘   └───────┘   └──────────────┘   └────────┘
                                                   ↓
┌──────┐   ┌────────────┐   ┌──────────┐   ┌────────┐
│ Save │ ← │    LLM     │ ← │ Conflict │ ← │ Filter │
└──────┘   └────────────┘   └──────────┘   └────────┘
                                  ↑
                          ┌──────────────┐
                          │ GraphExpand  │
                          │  (Neo4j)     │
                          └──────────────┘
```

| 노드 | 역할 |
|------|------|
| Profile | RDS에서 유저 나이/소득/이번달 소비 데이터 조회 |
| Embed | 카테고리별 소비 비중 기반 가중 평균 임베딩 생성 (Bedrock Titan 256차원) |
| VectorSearch | pgvector 코사인 유사도로 상위 30개 후보 선정 + Neo4j 카테고리 기반 추가 후보 + 보험 위험도 점수 필터링 |
| Rerank | klue-cross-encoder로 30개 → 7개 압축, 카드/보험/정책 타입별 쿼리 분리 |
| Filter | 나이/소득 조건 미충족 정책 제거, 지역 한정 정책 제거 |
| GraphExpand | Neo4j에서 상품 관계 트리플(IN_CATEGORY, TAGGED_WITH, SIMILAR_TO) 조회 |
| Conflict | 중복 신청 불가 정책 쌍 감지 (CONFLICTS_WITH 엣지) |
| LLM | Bedrock Claude Haiku가 최종 추천 선택 + 소비 데이터 기반 자연어 추천 사유 생성 |
| Save | 추천 결과를 recommend_card / recommend_insurance / recommend_policy 테이블에 저장 |

### 임베딩 품질 개선
- 단일 텍스트 임베딩 대신 **카테고리별 가중 평균 임베딩** 적용 → 코사인 유사도 0.19 → 0.35 향상
- 1024차원 → **256차원** 축소 → 차원의 저주 감소, 검색 정확도 유지

### Ablation Study 결과

| Stage | 구성 | LLM Judge |
|-------|------|-----------|
| Stage 1 | 벡터 검색만 | 55.1점 |
| Stage 2 | +Neo4j | 50.8점 |
| Stage 3 | +Reranker | 60.2점 |
| Stage 4 | +소득조건 필터 | 66.6점 |
| 현재 | +지역필터, Reranker타입분리, 보험위험도 | 72.9점 |

---

## 프로젝트 구조

```
app/
├── main.py                          # FastAPI 앱 초기화, 라우터 등록, SQS 폴링 시작
│
├── core/
│   ├── client/
│   │   ├── bedrock_client.py        # AWS Bedrock 연동 (Titan 임베딩, Claude 추천 생성)
│   │   ├── neo4j_client.py          # Neo4j AuraDB 연동 (트리플 조회, 후보 확장)
│   │   └── llm_client.py            # 인사이트 카드용 LLM 호출 (과소비 경고 문구 생성)
│   ├── config/
│   │   ├── database.py              # PostgreSQL 세션 팩토리 (SessionLocal)
│   │   ├── vector_database.py       # pgvector RDS 세션 팩토리 (VectorSessionLocal)
│   │   ├── sqs.py                   # SQS 폴링 루프, 메시지 라우팅
│   │   ├── redis.py                 # Redis Sentinel 연결 설정
│   │   ├── scheduler.py             # APScheduler 배치 스케줄러
│   │   └── settings.py              # 환경변수 로드 (DB_HOST, NEO4J_URI 등)
│   ├── common/
│   │   └── response.py              # CommonResponse[T] 공통 응답 래퍼
│   ├── error/
│   │   ├── exception.py             # BusinessException
│   │   └── handler.py               # 전역 예외 핸들러
│   ├── middleware/
│   │   └── auth.py                  # X-User-Id 헤더 기반 인증 미들웨어
│   └── utils/
│       └── tsid.py                  # TSID 생성기
│
├── domain/
│   ├── recommend_ai/                # AI 추천 파이프라인 (핵심)
│   │   ├── graph.py                 # LangGraph 파이프라인 조립 및 실행
│   │   ├── nodes.py                 # 파이프라인 노드 함수 전체 구현
│   │   ├── state.py                 # LangGraph State 타입 정의
│   │   ├── reranker.py              # klue-cross-encoder-v1 래퍼
│   │   ├── embed_service.py         # 상품 임베딩 텍스트 생성 및 저장
│   │   ├── graph_sync.py            # RDS → Neo4j 그래프 동기화
│   │   ├── router.py                # 내부 관리 API (추천 생성 트리거, 임베딩, 그래프 동기화)
│   │   └── entity.py                # AI 추천 관련 ORM 모델
│   │
│   ├── recommend/                   # 추천 결과 조회 API
│   │   ├── router.py                # GET /api/recommend/* 엔드포인트
│   │   ├── service.py               # 추천 결과 조회, 북마크 처리
│   │   ├── repository.py            # recommend_* 테이블 쿼리
│   │   ├── entity.py                # CardProduct, InsuranceProduct, PolicyProduct ORM
│   │   └── schema.py                # 추천 결과 응답 Pydantic 스키마
│   │
│   ├── insight/                     # AI 리포트
│   │   ├── router.py                # GET /api/ai/insights
│   │   ├── service.py               # 인사이트 카드 4종 생성 (주간트렌드, 과소비, 또래비교, 목표달성)
│   │   └── schema.py                # InsightResponse, InsightCardItem 스키마
│   │
│   ├── report/                      # 소비 데이터 및 리포트
│   │   ├── router.py                # GET /api/ai/report/* 엔드포인트
│   │   ├── service.py               # 리포트 상태 체크, 프로필/목표 설정
│   │   ├── repository.py            # WeeklyExpense, MonthlySummary, Goal 쿼리
│   │   ├── entity.py                # WeeklyExpense, MonthlySummary, Goal ORM 모델
│   │   └── schema.py                # 리포트 응답 스키마
│   │
│   ├── budget/
│   │   └── consumer.py              # SQS budget-ai-event 처리, 소비 데이터 업데이트
│   │
│   ├── profile/
│   │   ├── consumer.py              # SQS 온보딩 완료 이벤트 처리, user_profile 저장
│   │   └── entity.py                # UserProfile ORM 모델
│   │
│   └── sync/                        # 내부 동기화 API
│       ├── router.py
│       ├── service.py
│       ├── client.py
│       └── conflict.py              # 정책 충돌 관계 감지 및 저장
│
├── k8s/
│   ├── deployment.yaml              # EKS 배포 명세 (IMAGE_TAG_PLACEHOLDER 치환)
│   └── service.yaml                 # Kubernetes Service
│
├── Jenkinsfile                      # CI/CD 파이프라인
├── llm_benchmark.py                 # LLM Judge CI 평가 스크립트
└── Dockerfile
```

---

## API 명세

### AI Report (`/api/ai/report`)

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/ai/report/status` | AI 리포트 탭 진입 상태 체크. `profile_required`, `goal_required` 반환하여 클라이언트 화면 분기 |
| GET | `/api/ai/report/profile` | 프로필 미입력 필드 조회 (월소득, 생년월일, 성별) |
| POST | `/api/ai/report/profile` | 프로필 저장 |
| POST | `/api/ai/report/goal` | 이번 달 지출 목표 설정 |
| GET | `/api/ai/report/peers-comparison` | 또래 그룹(동일 나이대·소득 수준) 평균 소비와 비교 데이터 반환 |

### AI Insight (`/api/ai/insights`)

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/ai/insights` | 인사이트 카드 4종 반환. 주간 지출 BarChart, 카테고리 도넛차트, 과소비 경고, 또래 비교, 목표 달성 가능 여부 포함 |

### Recommend (`/api/recommend`)

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/recommend/cards` | AI 추천 카드 목록 조회 (AI 추천 사유 포함) |
| GET | `/api/recommend/insurances` | AI 추천 보험 목록 조회 |
| GET | `/api/recommend/policies` | AI 추천 청년 정책 목록 조회 (D-day 오름차순) |
| GET | `/api/recommend/policies/{policy_id}` | 청년 정책 상세 조회 |
| GET | `/api/recommend/bookmarks` | 북마크한 카드/보험/정책 통합 목록 |
| PATCH | `/api/recommend/bookmark/patch` | 북마크 설정/해제 토글 |

### Internal (`/internal/recommend`)

> API Gateway를 통해 외부에 노출되지 않는 내부 관리용 API

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/internal/recommend/generate/{user_id}` | 특정 유저 추천 파이프라인 수동 트리거 (백그라운드 실행) |
| POST | `/internal/recommend/embed/products` | 전체 카드/보험/정책 상품 임베딩 재생성 |
| POST | `/internal/recommend/sync/graph` | RDS → Neo4j 그래프 동기화 (`clear`, `include_similar` 파라미터) |
| GET | `/internal/recommend/graph/stats` | Neo4j 그래프 노드/엣지 통계 조회 |

---

## CI/CD

Jenkins 파이프라인은 다음 순서로 실행됩니다.

```
Checkout SCM
    ↓
SonarQube Analysis
    ↓
AWS ECR Authentication
    ↓
Docker Build & Push to ECR
    ↓
Deploy to AWS EKS  (kubectl apply + rollout status 대기)
    ↓
LLM Judge  (70점 미만 시 자동 rollback)
```

### LLM Judge

배포 후 자동으로 추천 품질을 평가합니다. 테스트 유저 7명의 소비 데이터를 RDS에 세팅하고 실제 추천 API를 호출한 뒤, Claude Judge가 3회 평균으로 100점 만점 평가합니다.

- 평가 기준: 혜택 적합성(40점), 추천 사유 품질(30점), 나이/소득 조건 충족(20점), 추천 다양성(10점)
- 통과 기준: 평균 70점 이상
- 실패 시: `kubectl rollout undo` 자동 롤백

---

## 환경변수

```env
# Database
DB_HOST=
DB_PORT=5432
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_SSLMODE=require

# AWS
AWS_REGION=ap-northeast-2
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

# Neo4j
NEO4J_URI=
NEO4J_USER=neo4j
NEO4J_PASSWORD=

# Anthropic
ANTHROPIC_API_KEY=

# Redis
REDIS_SENTINEL_HOSTS=
REDIS_SENTINEL_MASTER=

# SQS
SQS_BUDGET_QUEUE_URL=
SQS_PROFILE_QUEUE_URL=

# Auth
GATEWAY_SECRET_TOKEN=
```

---

## 참고 자료

- [FastAPI 공식 문서](https://fastapi.tiangolo.com)
- [LangGraph 공식 문서](https://langchain-ai.github.io/langgraph)
- [AWS Bedrock Titan Embeddings 문서](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)
- [pgvector GitHub](https://github.com/pgvector/pgvector)
- [Neo4j AuraDB 문서](https://neo4j.com/docs/aura)
- [bongsoo/klue-cross-encoder-v1 (HuggingFace)](https://huggingface.co/bongsoo/klue-cross-encoder-v1)
- [SQLAlchemy 2.0 공식 문서](https://docs.sqlalchemy.org/en/20)
- [LangSmith 문서](https://docs.smith.langchain.com)