"""
human_timing.py 单元测试

验证：
1. lognormal 分布截断到 [min, max]
2. 长停留概率符合预期（5%）
3. 函数返回值类型正确
4. 多次调用稳定（无 stall / 无 exception）
"""
from __future__ import annotations

import random
import time

import pytest

from jd_analytics.utils.human_timing import (
    human_pause,
    human_sleep,
    human_inter_page_delay,
    should_long_pause,
    human_typing_delay,
    human_mouse_move_step_delay,
    human_scroll_pause,
    human_initial_page_settle,
    human_reading_pause,
    LONG_PAUSE_PROBABILITY,
    LONG_PAUSE_RANGE,
)


class TestLognormalClip:
    def test_pause_in_range(self):
        random.seed(42)
        for _ in range(1000):
            v = human_pause(1.0, 5.0)
            assert 1.0 <= v <= 5.0

    def test_pause_min_equals_max(self):
        v = human_pause(2.0, 2.0)
        assert v == 2.0

    def test_pause_uniform_fallback(self):
        random.seed(42)
        v = human_pause(1.0, 2.0, lognormal=False)
        assert 1.0 <= v <= 2.0

    def test_pause_distribution_lognormal_long_tail(self):
        """lognormal 应该有长尾特性（多数接近 min，少数接近 max）"""
        random.seed(42)
        samples = [human_pause(1.0, 10.0) for _ in range(1000)]
        below_median = sum(1 for s in samples if s < 3.0)
        above_high = sum(1 for s in samples if s > 7.0)
        # 至少 50% 在下半部分，至少 5% 在上半部分（lognormal 长尾）
        assert below_median >= 400, f"Expected lognormal long-tail, got below_median={below_median}"
        assert above_high >= 20, f"Expected some samples near max, got above_high={above_high}"


class TestHumanSleep:
    def test_sleep_returns_duration(self):
        random.seed(42)
        t0 = time.monotonic()
        v = human_sleep(0.05, 0.1)
        elapsed = time.monotonic() - t0
        assert 0.05 <= v <= 0.1
        assert elapsed >= 0.05 - 0.01  # 实际 sleep 了

    def test_sleep_does_not_exceed_max(self):
        random.seed(42)
        for _ in range(100):
            t0 = time.monotonic()
            v = human_sleep(0.01, 0.05)
            elapsed = time.monotonic() - t0
            assert v <= 0.05
            assert elapsed < 0.2  # 不会 stall


class TestInterPageDelay:
    def test_returns_in_expected_range(self):
        random.seed(42)
        for _ in range(1000):
            v = human_inter_page_delay(3.0)
            # 95% 概率在 [3, 6]，5% 概率在 [10, 20]
            assert (3.0 <= v <= 6.0) or (10.0 <= v <= 20.0)

    def test_long_pause_occurs(self):
        """1000 次调用中应该出现长停留"""
        random.seed(42)
        long_pauses = 0
        for _ in range(1000):
            v = human_inter_page_delay(3.0)
            if v >= 10.0:
                long_pauses += 1
        # 期望 ~50 次（5%），允许浮动 [20, 100]
        assert 20 <= long_pauses <= 100, f"Expected ~50 long pauses, got {long_pauses}"


class TestShouldLongPause:
    def test_returns_bool(self):
        v = should_long_pause()
        assert isinstance(v, bool)

    def test_probability_roughly_correct(self):
        random.seed(42)
        true_count = sum(1 for _ in range(10000) if should_long_pause())
        # 期望 ~500 次（5%），允许 [300, 700]
        assert 300 <= true_count <= 700, f"Expected ~500, got {true_count}"

    def test_probability_one_always_true(self):
        random.seed(42)
        assert should_long_pause(1.0) is True

    def test_probability_zero_always_false(self):
        random.seed(42)
        assert should_long_pause(0.0) is False


class TestTypingDelay:
    def test_in_range(self):
        random.seed(42)
        for _ in range(1000):
            v = human_typing_delay()
            assert 0.05 <= v <= 0.25

    def test_lognormal_long_tail(self):
        random.seed(42)
        samples = [human_typing_delay() for _ in range(1000)]
        # 多数应小于 0.15（lognormal 中心偏小）
        small_count = sum(1 for s in samples if s < 0.15)
        assert small_count >= 600, f"Expected majority below 0.15s, got {small_count}"


class TestMouseMoveStepDelay:
    def test_in_range(self):
        random.seed(42)
        for _ in range(1000):
            v = human_mouse_move_step_delay()
            assert 0.01 <= v <= 0.03


class TestScrollPause:
    def test_in_range(self):
        random.seed(42)
        for _ in range(1000):
            v = human_scroll_pause()
            assert 0.8 <= v <= 2.5


class TestInitialPageSettle:
    def test_in_range(self):
        random.seed(42)
        for _ in range(1000):
            v = human_initial_page_settle()
            assert 2.0 <= v <= 5.0


class TestReadingPause:
    def test_in_range(self):
        random.seed(42)
        for _ in range(1000):
            v = human_reading_pause()
            assert 3.0 <= v <= 7.0


class TestConstants:
    def test_long_pause_probability(self):
        assert LONG_PAUSE_PROBABILITY == 0.05

    def test_long_pause_range(self):
        assert LONG_PAUSE_RANGE == (10.0, 20.0)
