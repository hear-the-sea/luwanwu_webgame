from __future__ import annotations


class FakeRedis:
    def __init__(self):
        self._zsets: dict[str, dict[int, float]] = {}

    def zadd(self, key: str, mapping: dict[int, float]):
        self._zsets.setdefault(key, {}).update({int(member): float(score) for member, score in mapping.items()})
        return True

    def expire(self, key: str, timeout: int):
        return True

    def zremrangebyscore(self, key: str, _min: str, cutoff: float):
        zset = self._zsets.get(key, {})
        before = len(zset)
        self._zsets[key] = {member: score for member, score in zset.items() if float(score) > float(cutoff)}
        return before - len(self._zsets[key])

    def zcard(self, key: str):
        return len(self._zsets.get(key, {}))

    def zunionstore(self, dest: str, keys, aggregate=None):
        del aggregate
        union: dict[int, float] = {}
        for key in keys:
            for member, score in self._zsets.get(key, {}).items():
                union[int(member)] = max(union.get(int(member), float("-inf")), float(score))
        self._zsets[dest] = union
        return len(union)
