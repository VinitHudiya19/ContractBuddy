"""
Provider error-mapping tests.

Free API tiers throttle often, and a throttled request is not a broken one: the
user needs to be told to wait, not to retry into another 429. These tests pin
the mapping from a provider SDK exception to the error the UI ends up showing.
"""
from __future__ import annotations

import pytest

from app.core.exceptions import AppError, LLMProviderError, LLMRateLimitError
from app.providers.llm.groq_provider import _wrap


class _StatusError(Exception):
    """Mirrors the SDK errors that carry an HTTP status."""

    def __init__(self, status_code: int, message: str = "boom") -> None:
        super().__init__(message)
        self.status_code = status_code


class TestRateLimitMapping:
    def test_429_status_maps_to_rate_limit(self):
        assert isinstance(_wrap(_StatusError(429), "request"), LLMRateLimitError)

    def test_rate_limit_text_maps_even_without_status(self):
        # Some SDK paths surface the limit only in the message body.
        exc = Exception("Error code: 429 - Rate limit reached for model `llama-3.3-70b`")
        assert isinstance(_wrap(exc, "stream"), LLMRateLimitError)

    def test_match_is_case_insensitive(self):
        assert isinstance(_wrap(Exception("RATE LIMIT exceeded"), "request"), LLMRateLimitError)

    @pytest.mark.parametrize("status", [400, 401, 500, 503])
    def test_other_statuses_stay_generic(self, status):
        wrapped = _wrap(_StatusError(status), "request")
        assert isinstance(wrapped, LLMProviderError)
        assert not isinstance(wrapped, LLMRateLimitError)

    def test_generic_error_keeps_context_for_debugging(self):
        wrapped = _wrap(Exception("connection reset"), "stream")
        assert "stream" in wrapped.message
        assert "connection reset" in wrapped.message


class TestRateLimitContract:
    """The stream endpoint forwards AppError.message verbatim, so it must be
    safe to show and must not leak provider internals."""

    def test_is_an_apperror_so_the_stream_handler_forwards_it(self):
        assert isinstance(LLMRateLimitError(), AppError)

    def test_still_an_llm_provider_error_for_existing_handlers(self):
        assert isinstance(LLMRateLimitError(), LLMProviderError)

    def test_status_and_code_are_distinguishable_from_our_own_limiter(self):
        err = LLMRateLimitError()
        assert err.status_code == 429
        assert err.code == "LLM_RATE_LIMITED"

    def test_message_tells_the_user_to_wait_and_hides_internals(self):
        message = LLMRateLimitError().message
        assert "wait" in message.lower()
        for leak in ("groq", "org_", "llama", "api_key"):
            assert leak not in message.lower()
