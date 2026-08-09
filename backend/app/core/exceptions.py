"""
Domain exceptions.

Each carries a stable machine `code` (surfaced in the JSON error envelope) and a
default HTTP status. The global handler in `middleware/error_handler.py` maps any
`AppError` to `{"error": {"code", "message", "request_id"}}` — a single, uniform
error shape across the whole API.
"""
from __future__ import annotationsclass AppError(Exception):
    """Base class for all handled application errors."""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, *, code: str | None = None):
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        super().__init__(self.message)


# ---- Auth / access ----
class AuthenticationError(AppError):
    code = "AUTHENTICATION_FAILED"
    status_code = 401
    message = "Invalid credentials."


class InvalidTokenError(AppError):
    code = "INVALID_TOKEN"
    status_code = 401
    message = "Token is invalid or expired."


class UnauthorizedAccessError(AppError):
    code = "UNAUTHORIZED_ACCESS"
    status_code = 403
    message = "You do not have permission to access this resource."


class InactiveUserError(AppError):
    code = "INACTIVE_USER"
    status_code = 403
    message = "This account has been deactivated."


# ---- Resource errors ----
class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404
    message = "Resource not found."


class DocumentNotFoundError(NotFoundError):
    code = "DOCUMENT_NOT_FOUND"
    message = "Document not found."


class ConversationNotFoundError(NotFoundError):
    code = "CONVERSATION_NOT_FOUND"
    message = "Conversation not found."


class UserAlreadyExistsError(AppError):
    code = "USER_ALREADY_EXISTS"
    status_code = 409
    message = "An account with this email already exists."


# ---- Validation / input ----
class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422
    message = "Request validation failed."


class UnsupportedFileTypeError(AppError):
    code = "UNSUPPORTED_FILE_TYPE"
    status_code = 415
    message = "Only PDF and DOCX files are supported."


class FileTooLargeError(AppError):
    code = "FILE_TOO_LARGE"
    status_code = 413
    message = "Uploaded file exceeds the maximum allowed size."


class DocumentNotReadyError(AppError):
    code = "DOCUMENT_NOT_READY"
    status_code = 409
    message = "Document is still processing and cannot be queried yet."


# ---- Infra / providers ----
class RateLimitExceededError(AppError):
    code = "RATE_LIMIT_EXCEEDED"
    status_code = 429
    message = "Too many requests. Please slow down."


class LLMProviderError(AppError):
    code = "LLM_PROVIDER_ERROR"
    status_code = 503
    message = "The language model provider is temporarily unavailable."


class LLMRateLimitError(LLMProviderError):
    """
    The *provider* throttled us — distinct from our own rate limiter. Worth its
    own type because the fix is "wait", not "retry now", and free API tiers hit
    this often enough that a generic error wastes the user's time.
    """

    code = "LLM_RATE_LIMITED"
    status_code = 429
    message = "The AI provider's rate limit was reached. Wait a minute and try again."


class EmbeddingProviderError(AppError):
    code = "EMBEDDING_PROVIDER_ERROR"
    status_code = 503
    message = "The embedding provider is temporarily unavailable."


class ServiceUnavailableError(AppError):
    code = "SERVICE_UNAVAILABLE"
    status_code = 503
    message = "A required backend service is unavailable."
