from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Shared utilities — use these in both ResponseCache and SharedRedisCache
# ---------------------------------------------------------------------------

PRIVACY_PATTERNS = re.compile(
    r"\b(balance|password|credit.card|ssn|social.security|user.\d+|account.\d+)\b",
    re.IGNORECASE,
)


def _is_uncacheable(query: str) -> bool:
    """Return True if query contains privacy-sensitive keywords."""
    return bool(PRIVACY_PATTERNS.search(query))


def _looks_like_false_hit(query: str, cached_key: str) -> bool:
    """Return True if query and cached key contain different 4-digit numbers (years, IDs)."""
    nums_q = set(re.findall(r"\b\d{4}\b", query))
    nums_c = set(re.findall(r"\b\d{4}\b", cached_key))
    return bool(nums_q and nums_c and nums_q != nums_c)


# ---------------------------------------------------------------------------
# In-memory cache (existing)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CacheEntry:
    key: str
    value: str
    created_at: float
    metadata: dict[str, str]


class ResponseCache:
    """Simple in-memory cache skeleton.

    TODO(student): Add a better semantic similarity function and false-hit guardrails.
    Use the module-level _is_uncacheable() and _looks_like_false_hit() helpers in your
    get() and set() methods.  For production, replace with SharedRedisCache.
    """

    def __init__(self, ttl_seconds: int, similarity_threshold: float):
        self.ttl_seconds = ttl_seconds
        self.similarity_threshold = similarity_threshold
        self._entries: list[CacheEntry] = []
        self.false_hit_log: list[dict[str, object]] = []

    def get(self, query: str) -> tuple[str | None, float]:
        if _is_uncacheable(query):
            return None, 0.0

        best_value: str | None = None
        best_key: str | None = None
        best_score = 0.0
        now = time.time()
        self._entries = [e for e in self._entries if now - e.created_at <= self.ttl_seconds]
        for entry in self._entries:
            score = self.similarity(query, entry.key)
            if score > best_score:
                best_score = score
                best_value = entry.value
                best_key = entry.key
        if best_key is not None and _looks_like_false_hit(query, best_key):
            self.false_hit_log.append(
                {"query": query, "cached_query": best_key, "similarity": round(best_score, 4)}
            )
            return None, best_score
        if best_score >= self.similarity_threshold:
            return best_value, best_score
        return None, best_score

    def set(self, query: str, value: str, metadata: dict[str, str] | None = None) -> None:
        metadata = metadata or {}
        if _is_uncacheable(query) or metadata.get("expected_risk") == "privacy":
            return
        self._entries.append(CacheEntry(query, value, time.time(), metadata or {}))

    @staticmethod
    def similarity(a: str, b: str) -> float:
        """Very small baseline similarity using token overlap.

        TODO(student): Improve with embeddings or a deterministic vectorizer.
        """
        left_text = a.lower().strip()
        right_text = b.lower().strip()
        if left_text == right_text:
            return 1.0

        left: set[str] = set(re.findall(r"\b\w+\b", left_text))
        right: set[str] = set(re.findall(r"\b\w+\b", right_text))
        if not left or not right:
            return 0.0

        token_overlap = len(left & right) / len(left | right)
        char_ngrams_left = ResponseCache._char_ngrams(left_text)
        char_ngrams_right = ResponseCache._char_ngrams(right_text)
        if char_ngrams_left and char_ngrams_right:
            char_overlap = len(char_ngrams_left & char_ngrams_right) / len(char_ngrams_left | char_ngrams_right)
        else:
            char_overlap = 0.0

        numeric_tokens_left = {token for token in left if token.isdigit()}
        numeric_tokens_right = {token for token in right if token.isdigit()}
        numeric_penalty = 0.0
        if numeric_tokens_left and numeric_tokens_right and numeric_tokens_left != numeric_tokens_right:
            numeric_penalty = 0.25

        return max(0.0, min(1.0, (0.65 * token_overlap) + (0.35 * char_overlap) - numeric_penalty))

    @staticmethod
    def _char_ngrams(text: str, size: int = 3) -> frozenset[str]:
        collapsed = re.sub(r"\s+", " ", text)
        if len(collapsed) < size:
            if collapsed:
                return frozenset({collapsed})
            empty: frozenset[str] = frozenset()
            return empty
        return frozenset(collapsed[index : index + size] for index in range(len(collapsed) - size + 1))


# ---------------------------------------------------------------------------
# Redis shared cache (new)
# ---------------------------------------------------------------------------


class SharedRedisCache:
    """Redis-backed shared cache for multi-instance deployments.

    TODO(student): Implement the get() and set() methods using Redis commands
    so that cache state is shared across multiple gateway instances.

    Data model (suggested):
        Key    = "{prefix}{query_hash}"   (Redis String namespace)
        Value  = Redis Hash with fields:  "query", "response"
        TTL    = Redis EXPIRE (automatic cleanup — no manual eviction)

    For similarity lookup: SCAN all keys with self.prefix, HGET each entry's
    "query" field, compute similarity locally via ResponseCache.similarity().

    Provided helpers:
        _is_uncacheable(query)          — True if privacy-sensitive
        _looks_like_false_hit(q, key)   — True if 4-digit numbers differ
        self._query_hash(query)         — deterministic short hash for Redis key
        ResponseCache.similarity(a, b)  — reuse your improved similarity function
    """

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int,
        similarity_threshold: float,
        prefix: str = "rl:cache:",
    ):
        import redis as redis_lib

        self.ttl_seconds = ttl_seconds
        self.similarity_threshold = similarity_threshold
        self.prefix = prefix
        self.false_hit_log: list[dict[str, object]] = []
        self._redis: Any = redis_lib.Redis.from_url(redis_url, decode_responses=True)

    def ping(self) -> bool:
        """Check Redis connectivity."""
        try:
            return bool(self._redis.ping())
        except Exception:
            return False

    def get(self, query: str) -> tuple[str | None, float]:
        """Look up a cached response from Redis.

        TODO(student): Implement cache lookup.  Suggested steps:
        1. Return (None, 0.0) if _is_uncacheable(query)
        2. Build exact-match key: f"{self.prefix}{self._query_hash(query)}"
        3. Try self._redis.hget(key, "response") — if found return (response, 1.0)
        4. Otherwise self._redis.scan_iter(f"{self.prefix}*") to iterate all cached keys
        5. For each key, HGET "query" field and compute
           ResponseCache.similarity(query, cached_query)
        6. Track best match that is >= self.similarity_threshold
        7. Before returning a match, check _looks_like_false_hit(); if true,
           append to self.false_hit_log and return (None, best_score)
        """
        if _is_uncacheable(query):
            return None, 0.0

        key = f"{self.prefix}{self._query_hash(query)}"
        try:
            exact_query = self._redis.hget(key, "query")
            exact_response = self._redis.hget(key, "response")
            if exact_query and exact_response and not _looks_like_false_hit(query, exact_query):
                return exact_response, 1.0

            best_value: str | None = None
            best_key: str | None = None
            best_score = 0.0
            for candidate_key in self._redis.scan_iter(f"{self.prefix}*"):
                cached_query = self._redis.hget(candidate_key, "query")
                cached_response = self._redis.hget(candidate_key, "response")
                if not cached_query or not cached_response:
                    continue
                score = ResponseCache.similarity(query, cached_query)
                if score > best_score:
                    best_score = score
                    best_key = cached_query
                    best_value = cached_response

            if best_key is not None and _looks_like_false_hit(query, best_key):
                self.false_hit_log.append(
                    {"query": query, "cached_query": best_key, "similarity": round(best_score, 4)}
                )
                return None, best_score

            if best_value is not None and best_score >= self.similarity_threshold:
                return best_value, best_score
        except Exception:
            return None, 0.0

        return None, 0.0

    def set(self, query: str, value: str, metadata: dict[str, str] | None = None) -> None:
        """Store a response in Redis with TTL.

        TODO(student): Implement cache storage.  Suggested steps:
        1. Return immediately if _is_uncacheable(query)
        2. Build key: f"{self.prefix}{self._query_hash(query)}"
        3. self._redis.hset(key, mapping={"query": query, "response": value})
        4. self._redis.expire(key, self.ttl_seconds)
        """
        metadata = metadata or {}
        if _is_uncacheable(query) or metadata.get("expected_risk") == "privacy":
            return

        key = f"{self.prefix}{self._query_hash(query)}"
        try:
            self._redis.hset(key, mapping={"query": query, "response": value})
            self._redis.expire(key, self.ttl_seconds)
        except Exception:
            return

    def flush(self) -> None:
        """Remove all entries with this cache prefix (for testing)."""
        for key in self._redis.scan_iter(f"{self.prefix}*"):
            self._redis.delete(key)

    def close(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            self._redis.close()

    @staticmethod
    def _query_hash(query: str) -> str:
        """Deterministic short hash for a query string."""
        return hashlib.md5(query.lower().strip().encode()).hexdigest()[:12]
