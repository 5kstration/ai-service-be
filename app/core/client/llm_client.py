# app/core/client/llm_client.py
import json
import logging
import anthropic

from app.core.config.settings import settings
from app.core.error.exception import BusinessException
from app.core.error.error_code import ErrorCode

logger = logging.getLogger(__name__)


# 모든 LLM 관련 API 호출과 응답 파싱을 담당하는 클라이언트 클래스.
class LLMClient:

    def __init__(self):
        # API 키는 필수이므로 초기화 시점에 반드시 확인.
        # 없을 시 앱 실행 자체를 막는 게 안전하다고 판단하여 ValueError 발생.
        if not settings.ANTHROPIC_API_KEY:
            logger.error("[LLMClient] ANTHROPIC_API_KEY가 설정되지 않았습니다.")
            raise ValueError("ANTHROPIC_API_KEY is required")
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def generate_report_message(
        self,
        user_id: str,
        total_expense: int,
        target_expense: int,
        achievement_rate: int,
        weekly_expenses: list,
    ) -> tuple[str, str]:
        """
        AI 리포트용 summary_message, saving_tip 생성.

        Args:
            user_id: 로깅용 사용자 ID
            total_expense: 이번 달 누적 총 지출
            target_expense: 목표 지출 (0이면 미설정)
            achievement_rate: 목표 달성률 (%)
            weekly_expenses: WeeklyExpense entity 리스트

        Returns:
            (summary_message, saving_tip) 튜플

        Raises:
            BusinessException(LLM_CALL_FAILED): API 호출 실패
            BusinessException(LLM_RESPONSE_PARSE_FAILED): 응답 파싱 실패
        """
        prompt = self._build_report_prompt(
            total_expense    = total_expense,
            target_expense   = target_expense,
            achievement_rate = achievement_rate,
            weekly_expenses  = weekly_expenses,
        )
        raw = self._call(user_id=user_id, prompt=prompt, max_tokens=500)
        return self._parse_report_response(raw, user_id)

    def _build_report_prompt(
        self,
        total_expense: int,
        target_expense: int,
        achievement_rate: int,
        weekly_expenses: list,
    ) -> str:
        """리포트 생성용 프롬프트 구성."""
        weekly_text = "\n".join([
            f"  {w.week}주차: {w.amount:,}원 ({w.start_date}~{w.end_date})"
            for w in weekly_expenses
        ]) or "  데이터 없음"

        return f"""
당신은 청년 맞춤형 금융 관리 앱의 AI 어시스턴트입니다.
아래 사용자의 이번 달 소비 데이터를 분석하여 친근하고 긍정적인 피드백을 제공해주세요.

[이번 달 소비 현황]
- 총 지출: {total_expense:,}원
- 목표 지출: {target_expense:,}원 {"(목표 미설정)" if target_expense == 0 else ""}
- 목표 달성률: {achievement_rate}%

[주차별 지출]
{weekly_text}

아래 JSON 형식으로만 응답해주세요. 다른 텍스트는 절대 포함하지 마세요.
{{
  "summary_message": "전체 소비 패턴에 대한 친근한 요약 (2~3문장, 이모지 없이)",
  "saving_tip": "현재 상황에서 실천 가능한 절약 팁 1가지 (실현 가능성이 있어야 함)(1문장)"
}}
"""

    def _call(self, user_id: str, prompt: str, max_tokens: int = 500) -> str:
        """
        Claude API 단건 호출.
        네트워크 오류, 타임아웃 등 모든 예외를 LLM_CALL_FAILED로 추상화.
        """
        try:
            message = self._client.messages.create(
                model      = settings.LLM_MODEL,
                max_tokens = max_tokens,
                messages   = [{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
            logger.info(f"[LLMClient] 응답 수신 완료 - user_id={user_id}")
            return raw
        except anthropic.APIConnectionError as e:
            logger.error(f"[LLMClient] 연결 실패 - user_id={user_id}, error={e}")
            raise BusinessException(ErrorCode.LLM_CALL_FAILED)
        except anthropic.APITimeoutError as e:
            logger.error(f"[LLMClient] 타임아웃 - user_id={user_id}, error={e}")
            raise BusinessException(ErrorCode.LLM_CALL_FAILED)
        except anthropic.APIStatusError as e:
            logger.error(f"[LLMClient] API 상태 오류 - status={e.status_code}, user_id={user_id}, error={e}")
            raise BusinessException(ErrorCode.LLM_CALL_FAILED)
        except Exception as e:
            logger.error(f"[LLMClient] 알 수 없는 오류 - user_id={user_id}, error={e}")
            raise BusinessException(ErrorCode.LLM_CALL_FAILED)

    def _parse_report_response(self, raw: str, user_id: str) -> tuple[str, str]:
        """
        LLM 응답 JSON 파싱.
        JSON 파싱 실패와 필드 누락을 분리하여 처리.
        """
        # 1. ```json ... ``` 형식 제거
        clean = raw.strip()
        if "```" in clean:
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip()

        # 2. JSON 파싱
        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError as e:
            logger.error(f"[LLMClient] JSON 파싱 실패 - raw={raw}, user_id={user_id}, error={e}")
            raise BusinessException(ErrorCode.LLM_RESPONSE_PARSE_FAILED)

        # 3. 필드 추출 및 검증
        summary    = parsed.get("summary_message", "").strip()
        saving_tip = parsed.get("saving_tip", "").strip()

        if not summary:
            logger.error(f"[LLMClient] summary_message 누락 - raw={raw}, user_id={user_id}")
            raise BusinessException(ErrorCode.LLM_RESPONSE_PARSE_FAILED)

        return summary, saving_tip


# 싱글톤 인스턴스
# service에서 매번 생성하지 않고 모듈 레벨에서 한 번만 생성.
llm_client = LLMClient()