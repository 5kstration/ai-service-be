from pydantic import BaseModel
from typing import TypeVar, Generic, Optional

T = TypeVar("T")

class CommonResponse(BaseModel, Generic[T]):
    success: bool
    message: str
    data: Optional[T] = None
    error_code: Optional[str] = None

    @classmethod
    def of(cls, data: T, message: str = "요청이 성공적으로 처리되었습니다."):
        return cls(success=True, message=message, data=data)

    @classmethod
    def error(cls, error_code: str, message: str):
        return cls(success=False, message=message, error_code=error_code)