from __future__ import annotations

import threading

from django.core.cache import cache

import core.utils.task_monitoring as task_monitoring
from core.utils.task_monitoring import (
    TASK_METRICS_CACHE_KEY,
    _metric_key,
    get_task_metrics,
    record_task_failure,
    record_task_retry,
    record_task_success,
    reset_task_metrics,
)


class TestTaskMonitoringCounters:
    """Test in-process task monitoring counters."""

    def setup_method(self):
        reset_task_metrics()

    def teardown_method(self):
        reset_task_metrics()

    def test_record_success_increments_counter(self):
        record_task_success("trade.refresh_shop_stock")
        record_task_success("trade.refresh_shop_stock")
        metrics = get_task_metrics()
        assert metrics["trade.refresh_shop_stock"]["success"] == 2
        assert metrics["trade.refresh_shop_stock"]["failure"] == 0
        assert metrics["trade.refresh_shop_stock"]["retry"] == 0

    def test_record_failure_increments_counter(self):
        record_task_failure("guests.complete_training")
        metrics = get_task_metrics()
        assert metrics["guests.complete_training"]["failure"] == 1
        assert metrics["guests.complete_training"]["success"] == 0

    def test_record_retry_increments_counter(self):
        record_task_retry("trade.settle_auction_round")
        record_task_retry("trade.settle_auction_round")
        record_task_retry("trade.settle_auction_round")
        metrics = get_task_metrics()
        assert metrics["trade.settle_auction_round"]["retry"] == 3
        assert metrics["trade.settle_auction_round"]["success"] == 0
        assert metrics["trade.settle_auction_round"]["failure"] == 0

    def test_multiple_tasks_tracked_independently(self):
        record_task_success("task_a")
        record_task_failure("task_b")
        record_task_retry("task_c")
        metrics = get_task_metrics()
        assert metrics["task_a"]["success"] == 1
        assert metrics["task_b"]["failure"] == 1
        assert metrics["task_c"]["retry"] == 1
        # Unrelated counters remain zero
        assert metrics["task_a"]["failure"] == 0
        assert metrics["task_b"]["success"] == 0

    def test_get_task_metrics_returns_snapshot(self):
        record_task_success("snapshot_task")
        snapshot = get_task_metrics()
        # Mutating the snapshot should not affect internal state
        snapshot["snapshot_task"]["success"] = 999
        assert get_task_metrics()["snapshot_task"]["success"] == 1

    def test_get_task_metrics_empty_when_no_records(self):
        metrics = get_task_metrics()
        assert metrics == {}

    def test_reset_clears_all_metrics(self):
        record_task_success("task_x")
        record_task_failure("task_y")
        record_task_retry("task_z")
        reset_task_metrics()
        assert get_task_metrics() == {}

    def test_record_after_reset_starts_fresh(self):
        record_task_success("restarted_task")
        record_task_success("restarted_task")
        reset_task_metrics()
        record_task_success("restarted_task")
        metrics = get_task_metrics()
        assert metrics["restarted_task"]["success"] == 1

    def test_metrics_are_persisted_via_cache_snapshot(self):
        record_task_success("cache_backed_task")
        # Registry records the task name.
        registry = cache.get(TASK_METRICS_CACHE_KEY)
        assert "cache_backed_task" in registry
        # Atomic counter key holds the correct value.
        assert cache.get(_metric_key("cache_backed_task", "success")) == 1

    def test_retry_also_records_degradation(self):
        from core.utils.degradation import CELERY_TASK_RETRY, get_degradation_counts, reset_degradation_counts

        reset_degradation_counts()
        record_task_retry("degradation_test_task")
        counts = get_degradation_counts()
        assert counts.get(CELERY_TASK_RETRY, 0) >= 1
        reset_degradation_counts()

    def test_concurrent_first_registration_keeps_both_tasks(self, monkeypatch):
        original_get = cache.get
        registry_read_barrier = threading.Barrier(2)

        def delayed_registry_get(key, *args, **kwargs):
            value = original_get(key, *args, **kwargs)
            if key == TASK_METRICS_CACHE_KEY:
                try:
                    registry_read_barrier.wait(timeout=0.2)
                except threading.BrokenBarrierError:
                    pass
            return value

        monkeypatch.setattr(task_monitoring.cache, "get", delayed_registry_get)

        threads = [
            threading.Thread(target=record_task_success, args=("thread_task_a",)),
            threading.Thread(target=record_task_success, args=("thread_task_b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        assert all(not thread.is_alive() for thread in threads)

        metrics = get_task_metrics()
        assert metrics["thread_task_a"]["success"] == 1
        assert metrics["thread_task_b"]["success"] == 1

    def test_concurrent_first_increment_same_task_counts_both_writes(self, monkeypatch):
        task_name = "shared_first_write_task"
        metric_key = _metric_key(task_name, "success")
        store: dict[str, int] = {}
        store_lock = threading.Lock()
        missing_key_barrier = threading.Barrier(2)

        class FakeCache:
            def incr(self, key, delta=1):
                with store_lock:
                    if key in store:
                        store[key] += delta
                        return store[key]

                try:
                    missing_key_barrier.wait(timeout=0.2)
                except threading.BrokenBarrierError:
                    pass
                raise ValueError("key does not exist")

            def add(self, key, value, timeout=None):
                del timeout
                with store_lock:
                    if key in store:
                        return False
                    store[key] = value
                    return True

            def set(self, key, value, timeout=None):
                del timeout
                with store_lock:
                    store[key] = value
                return True

        monkeypatch.setattr(task_monitoring, "cache", FakeCache())
        monkeypatch.setattr(task_monitoring, "_register_task_name", lambda *_args, **_kwargs: None)

        threads = [threading.Thread(target=record_task_success, args=(task_name,)) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        assert all(not thread.is_alive() for thread in threads)
        assert store[metric_key] == 2
