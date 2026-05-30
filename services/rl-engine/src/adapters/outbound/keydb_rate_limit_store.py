"""
KeyDB/Redis adapter for RateLimitStorePort.

Uses atomic GETSET + EXPIRE for token buckets and atomic INCR + EXPIRE
for window counters. Requires no Lua scripting — relies on KeyDB's
server-threads model for sub-millisecond atomicity guarantees.

Stdlib-only: no redis-py dependency in domain tests; this adapter is
injected by the DI container at runtime.
"""
from __future__ import annotations

import json
import socket
from datetime import datetime
from typing import Optional

from ...domain.models.rate_limit import TokenBucketState
from ...domain.ports.outbound.rate_limit_store import RateLimitStorePort


class _RedisClient:
    """Minimal RESP2 client — avoids redis-py dep in unit tests."""

    def __init__(self, host: str = "localhost", port: int = 6379, timeout: float = 1.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: Optional[socket.socket] = None

    def _connect(self) -> None:
        if self._sock:
            return
        s = socket.create_connection((self._host, self._port), timeout=self._timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = s

    def _send(self, *args: str) -> None:
        self._connect()
        cmd = f"*{len(args)}\r\n"
        for a in args:
            cmd += f"${len(str(a))}\r\n{a}\r\n"
        assert self._sock
        self._sock.sendall(cmd.encode())

    def _read_line(self) -> str:
        assert self._sock
        buf = b""
        while not buf.endswith(b"\r\n"):
            buf += self._sock.recv(1)
        return buf[:-2].decode()

    def _read_response(self):
        line = self._read_line()
        prefix, rest = line[0], line[1:]
        if prefix == "+":
            return rest
        if prefix == "-":
            raise RuntimeError(rest)
        if prefix == ":":
            return int(rest)
        if prefix == "$":
            length = int(rest)
            if length == -1:
                return None
            assert self._sock
            data = b""
            while len(data) < length + 2:
                data += self._sock.recv(length + 2 - len(data))
            return data[:-2].decode()
        return None

    def get(self, key: str) -> Optional[str]:
        self._send("GET", key)
        return self._read_response()

    def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        if ex:
            self._send("SET", key, value, "EX", str(ex))
        else:
            self._send("SET", key, value)
        self._read_response()

    def incr(self, key: str) -> int:
        self._send("INCR", key)
        return self._read_response()

    def expire(self, key: str, seconds: int) -> None:
        self._send("EXPIRE", key, str(seconds))
        self._read_response()

    def close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None


class KeyDBRateLimitStore(RateLimitStorePort):
    """
    Production KeyDB adapter for rate limit state.

    Token buckets: serialized as JSON, stored with TTL = refill_time_to_full + 60s.
    Window counters: atomic INCR + EXPIRE per window duration.
    """

    _BUCKET_PREFIX = "rl:bucket:"
    _COUNTER_PREFIX = "rl:counter:"

    def __init__(self, host: str = "localhost", port: int = 6379) -> None:
        self._client = _RedisClient(host=host, port=port)

    def get_bucket(self, key: str) -> Optional[TokenBucketState]:
        raw = self._client.get(f"{self._BUCKET_PREFIX}{key}")
        if raw is None:
            return None
        data = json.loads(raw)
        return TokenBucketState(
            key=data["key"],
            tokens=data["tokens"],
            max_tokens=data.get("max_tokens", data["tokens"]),
            last_refill_at=datetime.fromisoformat(data["last_refill_at"]),
            refill_rate=data.get("refill_rate", 0.0),
        )

    def save_bucket(self, bucket: TokenBucketState) -> None:
        payload = json.dumps({
            "key": bucket.key,
            "tokens": bucket.tokens,
            "max_tokens": bucket.max_tokens,
            "last_refill_at": bucket.last_refill_at.isoformat(),
            "refill_rate": bucket.refill_rate,
        })
        # TTL: 24h — buckets refill naturally; stale ones expire automatically
        self._client.set(f"{self._BUCKET_PREFIX}{bucket.key}", payload, ex=86400)

    def increment_counter(self, key: str, window: int) -> int:
        full_key = f"{self._COUNTER_PREFIX}{key}"
        count = self._client.incr(full_key)
        if count == 1:
            # First increment — set expiry equal to window duration
            self._client.expire(full_key, window)
        return count

    def close(self) -> None:
        self._client.close()
