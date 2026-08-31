"""
人类行为仿真 - 时序通用层（Layer A）

纯函数，无浏览器依赖。DrissionPage 路线和 scrapy 路线共用。

设计原理：
- 人类反应时间符合 lognormal 分布（多数快，少数慢，长尾）
- 均匀分布（random.uniform）是机器人特征
- 5% 概率长停留模拟"阅读"行为
- 所有停顿都有截断上下界，避免极端值 stall

参考：
- 人类反应时间 lognormal 拟合：σ ≈ 0.7, μ ≈ 0
- 阅读停留时间分布：lognormal 长尾，均值 3-5s
"""
from __future__ import annotations

import random
import time
from typing import Final

# lognormal 分布参数（人类反应时间拟合）
DEFAULT_MU: Final[float] = 0.0
DEFAULT_SIGMA: Final[float] = 0.7

# 长停留概率（模拟人类偶尔的"阅读"行为）
LONG_PAUSE_PROBABILITY: Final[float] = 0.05
LONG_PAUSE_RANGE: Final[tuple[float, float]] = (10.0, 20.0)


def _lognormal_clipped(
    min_sec: float,
    max_sec: float,
    mu: float = DEFAULT_MU,
    sigma: float = DEFAULT_SIGMA,
) -> float:
    """生成 lognormal 分布的停顿时间，截断到 [min, max]

    lognormal 长尾特性：多数样本接近 min，少数样本接近 max（符合人类反应时间分布）
    截断保证不会出现极端 stall（如 100s）
    """
    raw = random.lognormvariate(mu, sigma)
    # 用 sigmoid-like 函数映射到 [min, max]，保持长尾特性
    # raw / (raw + 1.5) → 0~1 之间，多数接近 0，少数接近 1
    scaled = min_sec + (max_sec - min_sec) * (raw / (raw + 1.5))
    return max(min_sec, min(max_sec, scaled))


def human_pause(
    min_sec: float,
    max_sec: float,
    *,
    lognormal: bool = True,
) -> float:
    """人类停顿时间（lognormal 分布）

    多数停顿接近 min_sec，少数接近 max_sec（长尾）
    替代 random.uniform(min, max) 的均匀分布

    Args:
        min_sec: 最小停顿
        max_sec: 最大停顿
        lognormal: True 用 lognormal，False 回退到 uniform（测试用）

    Returns:
        实际停顿秒数（已 sleep）
    """
    if not lognormal:
        return random.uniform(min_sec, max_sec)
    return _lognormal_clipped(min_sec, max_sec)


def human_sleep(
    min_sec: float,
    max_sec: float,
    *,
    lognormal: bool = True,
) -> float:
    """人类停顿并 sleep（human_pause 的 sleep 包装）

    Returns:
        实际 sleep 秒数
    """
    delay = human_pause(min_sec, max_sec, lognormal=lognormal)
    time.sleep(delay)
    return delay


def human_inter_page_delay(base_sleep: float = 3.0) -> float:
    """翻页间延迟（带 5% 概率长停留）

    模拟人类翻页行为：
    - 95% 情况：lognormal 短停顿（base_sleep ~ base_sleep+3s）
    - 5% 情况：长停留 10-20s（模拟阅读当前页内容）

    Args:
        base_sleep: 基础停顿秒数（默认 3.0）

    Returns:
        sleep 秒数（已 sleep）
    """
    if random.random() < LONG_PAUSE_PROBABILITY:
        delay = random.uniform(*LONG_PAUSE_RANGE)
    else:
        delay = _lognormal_clipped(base_sleep, base_sleep + 3.0)
    time.sleep(delay)
    return delay


def should_long_pause(probability: float = LONG_PAUSE_PROBABILITY) -> bool:
    """决策是否触发长停留（不 sleep，只返回 bool）"""
    return random.random() < probability


def human_typing_delay() -> float:
    """逐字符输入间隔（lognormal，50-250ms）

    人类打字速度：均值 ~100ms，σ=0.4
    """
    return _lognormal_clipped(0.05, 0.25, mu=0.1, sigma=0.4)


def human_mouse_move_step_delay() -> float:
    """鼠标轨迹单步间隔（10-30ms）

    贝塞尔曲线鼠标移动时每步之间的停顿
    """
    return _lognormal_clipped(0.01, 0.03, mu=0.0, sigma=0.3)


def human_scroll_pause() -> float:
    """滚动段间停顿（0.8-2.5s，模拟阅读）"""
    return _lognormal_clipped(0.8, 2.5)


def human_initial_page_settle() -> float:
    """页面加载后初始等待（2-5s，让页面完全渲染）"""
    return _lognormal_clipped(2.0, 5.0)


def human_reading_pause() -> float:
    """阅读停留（3-7s，人类看页面内容的时间）"""
    return _lognormal_clipped(3.0, 7.0)
