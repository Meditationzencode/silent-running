from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from engine import InvalidAction


class ApiError(Exception):
    def __init__(self, status_code: int, error: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error = error
        self.detail = detail


def error_body(error: str, detail: str) -> dict[str, str]:
    return {"error": error, "detail": detail}


def first_validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "request body is malformed"

    first = errors[0]
    location = ".".join(
        str(part) for part in first.get("loc", ()) if part not in ("body", "query")
    )
    message = first.get("msg", "invalid value")
    return f"{location}: {message}" if location else message


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=error_body(exc.error, exc.detail)
        )

    @app.exception_handler(InvalidAction)
    async def _invalid_action(request: Request, exc: InvalidAction) -> JSONResponse:
        return JSONResponse(
            status_code=400, content=error_body(exc.code, exc.detail)
        )

    @app.exception_handler(RequestValidationError)
    async def _malformed(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=error_body("malformed_request", first_validation_message(exc)),
        )
