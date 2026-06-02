from fastapi import Header, HTTPException
from app.core.config.settings import settings

async def get_current_user(
    x_user_id: str = Header(None),
    x_gateway_token: str = Header(None),
):
    if x_gateway_token != settings.GATEWAY_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Gateway 인증 실패")
    if not x_user_id:
        raise HTTPException(status_code=401, detail="인증 정보가 없습니다.")
    return x_user_id