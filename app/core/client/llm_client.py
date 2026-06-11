# app/core/client/llm_client.py
import json
import logging
import anthropic
import boto3

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
        monthly_summary: list = None,
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
            monthly_summary  = monthly_summary,
        )
        raw = self._call(user_id=user_id, prompt=prompt, max_tokens=500)
        return self._parse_report_response(raw, user_id)

    def _build_report_prompt(
        self,
        total_expense: int,
        target_expense: int,
        achievement_rate: int,
        weekly_expenses: list,
        monthly_summary: list = None,  # 추가
    ) -> str:
        weekly_text = "\n".join([
            f"  {w.week}주차: {w.amount:,}원 ({w.start_date}~{w.end_date})"
            for w in weekly_expenses
        ]) or "  데이터 없음"

        # 추가
        category_text = ""
        if monthly_summary:
            category_text = "\n[카테고리별 지출]\n" + "\n".join([
                f"  {s.category}: {s.amount:,}원 ({int(s.ratio or 0)}%)"
                for s in monthly_summary
            ])

        return f"""
당신은 청년 맞춤형 금융 관리 앱의 AI 어시스턴트입니다.
아래 사용자의 이번 달 소비 데이터를 분석하여 친근하고 긍정적인 피드백을 제공해주세요.

[이번 달 소비 현황]
- 총 지출: {total_expense:,}원
- 목표 지출: {target_expense:,}원 {"(목표 미설정)" if target_expense == 0 else ""}
- 목표 달성률: {achievement_rate}%

[주차별 지출]
{weekly_text}
{category_text}

[응답 규칙]
- 친근하고 응원하는 톤으로 작성하세요.
- 이모지는 절대 사용하지 마세요.
- 다른 텍스트는 절대 포함하지 말고 순수 JSON 형식으로만 응답하세요.

[출력 예시]
{{
  "summary_message": "이번 달은 3주차에 지출이 몰리면서 아쉽게도 목표 금액을 초과했어요. 하지만 4주차에는 다시 지출을 안정적으로 관리한 모습이 아주 멋집니다. 다음 달에는 조금만 더 예산 배분에 신경 쓰면 목표를 꼭 달성할 수 있을 거예요!",
  "saving_tip": "지출이 가장 컸던 3주차의 소비 내역을 점검해 보고, 불필요한 충동구매를 줄여보는 건 어떨까요?"
}}

아래 JSON 형식으로만 응답해주세요.
{{
    "summary_message": "이번 달 소비 패턴을 분석하여 잘하고 있는 점과 개선할 점을 포함해 친근하게 2~3문장으로 작성. 단순 "이번달 nn%절약했어요"와같은 단문 금지. 카테고리별 지출 비중과 목표 달성 여부를 구체적으로 언급. 이모지 없이",
    "saving_tip": "가장 지출이 많은 카테고리를 기반으로 당장 실천 가능한 구체적인 절약 팁 1가지 (1~2문장)"
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
            logger.error(f"[LLMClient] JSON 파싱 실패 - user_id={user_id}, raw_len={len(raw)}, error={e}")
            raise BusinessException(ErrorCode.LLM_RESPONSE_PARSE_FAILED)

        # 3. 필드 추출 및 검증
        summary    = parsed.get("summary_message", "").strip()
        saving_tip = parsed.get("saving_tip", "").strip()

        if not summary:
            logger.error(f"[LLMClient] summary_message 누락 - user_id={user_id}, raw_len={len(raw)}")
            raise BusinessException(ErrorCode.LLM_RESPONSE_PARSE_FAILED)

        return summary, saving_tip


# 싱글톤 인스턴스
# service에서 매번 생성하지 않고 모듈 레벨에서 한 번만 생성.
llm_client = LLMClient()