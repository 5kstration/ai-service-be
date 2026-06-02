# app/core/error/error_code.py
from enum import Enum
from fastapi import status

# 에러 코드 규칙 : HTTP 상태코드 앞 3자리 + 도메인별 시퀀스 2자리
# ex) 40401 = 404 + 01
class ErrorCode(Enum):

    # =============================================
    # 공통
    # =============================================
    INVALID_REQUEST    = (status.HTTP_400_BAD_REQUEST,           "40001", "잘못된 요청입니다.")
    UNAUTHORIZED       = (status.HTTP_401_UNAUTHORIZED,          "40101", "인증이 필요합니다.")
    FORBIDDEN          = (status.HTTP_403_FORBIDDEN,             "40301", "접근 권한이 없습니다.")
    NOT_FOUND          = (status.HTTP_404_NOT_FOUND,             "40401", "리소스를 찾을 수 없습니다.")
    NOT_ALLOWED        = (status.HTTP_405_METHOD_NOT_ALLOWED,    "40501", "허용되지 않은 메서드입니다.")
    CONFLICT           = (status.HTTP_409_CONFLICT,              "40901", "이미 존재하는 리소스입니다.")
    TIMEOUT            = (status.HTTP_408_REQUEST_TIMEOUT,       "40801", "요청 시간이 초과되었습니다.")
    TOO_MANY_REQUEST   = (status.HTTP_429_TOO_MANY_REQUESTS,     "42901", "요청 횟수를 초과했습니다.")
    DB_ERROR           = (status.HTTP_500_INTERNAL_SERVER_ERROR, "50001", "데이터베이스 오류가 발생했습니다.")
    INTERNAL_ERROR     = (status.HTTP_500_INTERNAL_SERVER_ERROR, "50002", "알 수 없는 서버 오류가 발생했습니다.")
    EXTERNAL_API_ERROR = (status.HTTP_502_BAD_GATEWAY,           "50201", "외부 API 호출에 실패했습니다.")

    # =============================================
    # Redis
    # 캐시 계층 에러는 대부분 서비스를 중단시키지 않고 fallback 처리.
    # 단, 클라이언트에 직접 노출할 필요가 있는 케이스만 에러 코드로 정의.
    # =============================================
    REDIS_CONNECTION_ERROR    = (status.HTTP_500_INTERNAL_SERVER_ERROR, "50030", "캐시 서버에 연결할 수 없습니다.")
    REDIS_READ_ERROR          = (status.HTTP_500_INTERNAL_SERVER_ERROR, "50031", "캐시 데이터 조회에 실패했습니다.")
    REDIS_WRITE_ERROR         = (status.HTTP_500_INTERNAL_SERVER_ERROR, "50032", "캐시 데이터 저장에 실패했습니다.")
    REDIS_CORRUPTED_DATA      = (status.HTTP_500_INTERNAL_SERVER_ERROR, "50033", "캐시 데이터가 손상되었습니다. DB에서 재조회합니다.")
    REDIS_LOCK_ACQUIRE_FAILED = (status.HTTP_409_CONFLICT,              "40902", "현재 다른 요청이 처리 중입니다. 잠시 후 다시 시도해주세요.")

    # =============================================
    # 리포트
    # =============================================
    REPORT_NOT_FOUND               = (status.HTTP_404_NOT_FOUND,             "40410", "이번 달 리포트가 아직 없어요")
    REPORT_ALREADY_GENERATING      = (status.HTTP_409_CONFLICT,              "40910", "리포트를 생성 중이에요. 잠시만 기다려주세요.")
    REPORT_GENERATE_FAILED         = (status.HTTP_500_INTERNAL_SERVER_ERROR, "50010", "리포트 생성에 실패했습니다. 잠시 후 다시 시도해주세요.")
    REPORT_CACHE_MISS_DB_FALLBACK  = (status.HTTP_200_OK,                    "20010", "캐시 미스로 DB에서 조회했습니다.")  # 내부 로깅용

    # =============================================
    # 인사이트
    # =============================================
    INSIGHT_NOT_FOUND             = (status.HTTP_404_NOT_FOUND, "40420", "인사이트 데이터가 없습니다.")
    INSIGHT_CACHE_MISS_DB_FALLBACK = (status.HTTP_200_OK,       "20020", "캐시 미스로 DB에서 조회했습니다.")  # 내부 로깅용

    # =============================================
    # 추천 (카드 / 보험 / 정책)
    # =============================================
    RECOMMEND_NOT_FOUND           = (status.HTTP_404_NOT_FOUND, "40430", "추천 데이터가 없습니다.")
    RECOMMEND_POLICY_NOT_FOUND    = (status.HTTP_404_NOT_FOUND, "40431", "해당 정책을 찾을 수 없습니다.")
    RECOMMEND_CARD_NOT_FOUND      = (status.HTTP_404_NOT_FOUND, "40432", "해당 카드 추천 정보를 찾을 수 없습니다.")
    RECOMMEND_INSURANCE_NOT_FOUND = (status.HTTP_404_NOT_FOUND, "40433", "해당 보험 추천 정보를 찾을 수 없습니다.")
    RECOMMEND_CACHE_MISS_DB_FALLBACK = (status.HTTP_200_OK,     "20030", "캐시 미스로 DB에서 조회했습니다.")  # 내부 로깅용

    # =============================================
    # 북마크
    # =============================================
    BOOKMARK_NOT_FOUND        = (status.HTTP_404_NOT_FOUND,    "40440", "북마크를 찾을 수 없습니다.")

    # =============================================
    # 목표 (Goal)
    # =============================================
    GOAL_NOT_FOUND      = (status.HTTP_404_NOT_FOUND, "40450", "이번 달 목표가 설정되지 않았습니다.")
    GOAL_ALREADY_EXISTS = (status.HTTP_409_CONFLICT,  "40951", "이번 달 목표가 이미 설정되어 있습니다.")

    # =============================================
    # 유저 프로필 (UserProfile)
    # =============================================
    PROFILE_REQUIRED    = (status.HTTP_202_ACCEPTED,  "20201", "서비스 이용을 위해 프로필 정보 입력이 필요합니다.")
    PROFILE_NOT_FOUND   = (status.HTTP_404_NOT_FOUND, "40460", "유저 프로필 정보가 없습니다.")

    # =============================================
    # SQS 발행
    # =============================================
    SQS_PUBLISH_FAILED  = (status.HTTP_500_INTERNAL_SERVER_ERROR, "50040", "이벤트 발행에 실패했습니다.")

    # =============================================
    # LLM
    # =============================================
    LLM_CALL_FAILED           = (status.HTTP_502_BAD_GATEWAY,           "50210", "AI 분석 요청에 실패했습니다. 잠시 후 다시 시도해주세요.")
    LLM_RESPONSE_PARSE_FAILED = (status.HTTP_500_INTERNAL_SERVER_ERROR, "50011", "AI 응답 파싱에 실패했습니다.")

    # =============================================
    # 외부 서비스
    # =============================================
    AUTH_SERVICE_UNAVAILABLE   = (status.HTTP_502_BAD_GATEWAY, "50220", "인증 서비스에 연결할 수 없습니다.")
    BUDGET_SERVICE_UNAVAILABLE = (status.HTTP_502_BAD_GATEWAY, "50221", "가계부 서비스에 연결할 수 없습니다.")

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code        = code
        self.message     = message