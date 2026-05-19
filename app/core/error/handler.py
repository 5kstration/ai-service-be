from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.error.exception import BusinessException
from app.core.common.response import CommonResponse

async def business_exception_handler(request: Request, exc: BusinessException):
    return JSONResponse(
        status_code=exc.status_code,
        content=CommonResponse.error(
            error_code=exc.error_code,
            message=exc.message
        ).model_dump()
    )