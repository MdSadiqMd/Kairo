"""Cache-aware routing.

vLLM/SGLang prefix caching (RadixAttention) is per-instance. Naive
round-robin scatters identical prefixes across replicas and keeps the hit rate
near zero. We therefore:

1. Hash a stable prefix key (system prompt + policy + tenant boilerplate) and
   route it via consistent hashing to a preferred replica, so identical
   prefixes land on the same instance and reuse its cache.
2. Keep multi-turn sessions pinned to the replica that already cached their
   growing prefix (session affinity).
3. Fall back to the least-loaded replica when the preferred one is saturated —
   trading a cache miss for latency rather than queueing behind a hot replica.

Consistent hashing (a hash ring with virtual nodes) means adding/removing a
replica only remaps ~1/N of keys, so a scale event does not cold-invalidate
every cache.
"""

from __future__ import annotations

import bisect
import hashlib


def stable_prefix_key(system_and_policy: str, tenant_id: str) -> str:
    """Key over the parts of a request that recur across calls.

    Only the cache-friendly prefix (system/developer/policy text + tenant) is
    hashed — never the user's turn, which is unique per request.
    """
    h = hashlib.sha256()
    h.update(tenant_id.encode())
    h.update(b"\x00")
    h.update(system_and_policy.encode())
    return h.hexdigest()


def _hash_ring_point(value: str) -> int:
    return int.from_bytes(hashlib.blake2b(value.encode(), digest_size=8).digest(), "big")


class ConsistentHashRouter:
    """Maps prefix keys to replica indices on a virtual-node hash ring."""

    def __init__(self, replicas: int, *, virtual_nodes: int = 128) -> None:
        self.set_replicas(replicas, virtual_nodes=virtual_nodes)

    def set_replicas(self, replicas: int, *, virtual_nodes: int = 128) -> None:
        self._replicas = max(replicas, 1)
        self._vnodes = virtual_nodes
        self._ring: list[tuple[int, int]] = []
        for r in range(self._replicas):
            for v in range(virtual_nodes):
                self._ring.append((_hash_ring_point(f"{r}:{v}"), r))
        self._ring.sort()
        self._points = [p for p, _ in self._ring]

    def preferred_replica(self, prefix_key: str) -> int:
        if not prefix_key:
            return 0
        point = _hash_ring_point(prefix_key)
        idx = bisect.bisect(self._points, point) % len(self._ring)
        return self._ring[idx][1]

    def pick(
        self,
        prefix_key: str,
        *,
        queue_depths: list[int] | None = None,
        failover_threshold: int = 32,
    ) -> int:
        """Return a replica index, honoring affinity but shedding to the
        least-loaded replica when the preferred one is saturated."""
        preferred = self.preferred_replica(prefix_key)
        if not queue_depths:
            return preferred
        if preferred < len(queue_depths) and queue_depths[preferred] <= failover_threshold:
            return preferred
        return min(range(len(queue_depths)), key=lambda i: queue_depths[i])
