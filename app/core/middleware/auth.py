from fastapi import Header, HTTPException

async def get_current_user(x_user_id: str = Header(None)):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="인증 정보가 없습니다.")
    return x_user_id

