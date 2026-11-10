"""Stable public errors. Never include remote HTML, exception text or request URLs."""

from __future__ import annotations

import requests


class PortalError(RuntimeError):
    code = "PORTAL_ERROR"
    retryable = False


class AuthenticationError(PortalError):
    code = "AUTHENTICATION_FAILED"


class MFARequired(AuthenticationError):
    code = "MFA_REQUIRED"


class AuthenticationLoop(AuthenticationError):
    code = "AUTHENTICATION_LOOP"


class SessionExpired(AuthenticationError):
    code = "SESSION_EXPIRED"


class StructureChanged(PortalError):
    code = "STRUCTURE_CHANGED"


class DataUnavailable(PortalError):
    code = "DATA_UNAVAILABLE"


class TransportError(PortalError):
    code = "NETWORK_ERROR"
    retryable = True


class RequestTimeout(TransportError):
    code = "TIMEOUT"


class RateLimited(TransportError):
    code = "RATE_LIMITED"


class ServiceUnavailable(TransportError):
    code = "SERVICE_UNAVAILABLE"


class ResponseTooLarge(PortalError):
    code = "RESPONSE_TOO_LARGE"


class ReadStateChangeRequired(PortalError):
    code = "READ_STATE_CHANGE_REQUIRED"


class ReadStateUnknown(PortalError):
    code = "READ_STATE_UNKNOWN"


class ReadStateVerificationFailed(PortalError):
    code = "READ_STATE_VERIFICATION_FAILED"


class NoticeNotFound(PortalError):
    code = "NOTICE_NOT_FOUND"


class NoticeAmbiguous(PortalError):
    code = "NOTICE_AMBIGUOUS"


def public_error(exc: Exception) -> dict[str, object]:
    if isinstance(exc, PortalError):
        code, retryable = exc.code, exc.retryable
    elif isinstance(exc, requests.Timeout):
        code, retryable = "TIMEOUT", True
    elif isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else 0
        code = {401: "SESSION_EXPIRED", 403: "ACCESS_DENIED", 404: "NOT_FOUND", 429: "RATE_LIMITED"}.get(
            status, "SERVICE_UNAVAILABLE" if status >= 500 else "HTTP_ERROR"
        )
        retryable = status == 429 or status >= 500
    elif isinstance(exc, requests.RequestException):
        code, retryable = "NETWORK_ERROR", True
    elif isinstance(exc, ValueError):
        code, retryable = "INVALID_INPUT", False
    else:
        code, retryable = "INTERNAL_ERROR", False
    return {"code": code, "retryable": retryable}
