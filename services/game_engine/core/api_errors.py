from typing import Any


class ApiProblem(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        fields: dict[str, Any] | None = None,
        request_id: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields or {}
        self.request_id = request_id

    def detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "fields": self.fields,
            "request_id": self.request_id,
        }
