"""
Shared page-size limits for list endpoints.

The cap is what matters: without it a single request can be made to serialize a
user's entire history, and the cost of that grows with the account rather than
with the request.
"""
from __future__ import annotations

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
