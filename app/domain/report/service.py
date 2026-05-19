from app.core.config.database import SessionLocal
from app.core.error.exception import BusinessException

class ReportService:

    def get_monthly_report(self, user_id: str, year: int, month: int):
        db = SessionLocal()
        try:
            # TODO: DB에서 리포트 조회
            # 없으면 404
            raise BusinessException(
                error_code="40401",
                message="리포트가 존재하지 않습니다. 생성을 요청해주세요.",
                status_code=404
            )
        finally:
            db.close()

    def generate_report(self, user_id: str, year: int, month: int):
        # TODO: LLM 호출 비동기 처리
        pass