"""
新鲜度衰减 + 赏味窗口计算

⚠ 实验性参数：H（烘焙硬度）和 D（处理法密度）会调整衰减斜率。
  这两个系数基于咖啡物理直觉估算，尚未经大样本实测验证。
  系统会通过季度个人公式逐步校正实际误差。
"""

from datetime import date, datetime


FLAVOR_WINDOWS = {
    "washed":    {"open": 7,  "best_start": 14, "best_end": 28},
    "natural":   {"open": 14, "best_start": 21, "best_end": 42},
    "honey":     {"open": 10, "best_start": 18, "best_end": 35},
    "anaerobic": {"open": 10, "best_start": 18, "best_end": 35},
}

# 两段斜率基准值
RESTING_DAYS = 7          # 养豆期天数
RESTING_SLOPE = 0.08      # 养豆期每天偏移幅度（格）
AGING_SLOPE = 0.015       # 老化期每天偏移（格），调细方向


def days_since_roast(roast_date: str) -> int:
    """计算距离烘焙日期的天数"""
    rd = datetime.strptime(roast_date, "%Y-%m-%d").date()
    return (date.today() - rd).days


def freshness_offset(days: int, H: float = 1.0, D: float = 1.0) -> float:
    """
    返回新鲜度引起的研磨偏移量（β-normalized，需乘 β 转换为格数）。

    H（烘焙硬度，实验性）：
      浅烘豆更硬，老化慢 → aging_slope 除以 H（H 越大斜率越小）
      dark=0.7 → 老化快；light=1.2 → 老化慢

    D（处理法密度，实验性）：
      日晒/厌氧豆残留更多发酵产物，养豆期波动更大 → resting_slope 除以 D
      anaerobic=1.1 → 养豆期相对稳定；natural=0.9 → 波动更大
    """
    if days <= 0:
        return 0.0

    # ⚠ 实验性：H/D 调整斜率，默认 1.0 = 无修正
    aging_slope = AGING_SLOPE / H    # 硬度越高老化越慢
    resting_slope = RESTING_SLOPE / D  # 密度越低养豆期波动越大

    if days <= RESTING_DAYS:
        return round(resting_slope * days, 3)
    else:
        aging_days = days - RESTING_DAYS
        return round(aging_slope * aging_days, 3)


def flavor_stage(days: int, process_method: str) -> dict:
    """
    返回当前赏味阶段信息。
    process_method: "washed" / "natural" / "honey" / "anaerobic"
    """
    w = FLAVOR_WINDOWS.get(process_method, FLAVOR_WINDOWS["washed"])
    open_day = w["open"]
    best_start = w["best_start"]
    best_end = w["best_end"]

    if days < open_day:
        remaining = open_day - days
        return {
            "stage": "resting",
            "label":    "养豆期",
            "label_en": "Resting",
            "message":    f"建议再等 {remaining} 天，参数不稳定",
            "message_en": f"Wait {remaining} more day(s) — flavour not stable yet",
            "days_remaining": remaining,
            "is_stable": False,
        }
    elif days < best_start:
        days_to_best = best_start - days
        return {
            "stage": "opening",
            "label":    "开窗期",
            "label_en": "Opening",
            "message":    f"正在开窗，再等 {days_to_best} 天进入最佳期",
            "message_en": f"Opening up — {days_to_best} day(s) to peak window",
            "days_remaining": days_to_best,
            "is_stable": True,
        }
    elif days <= best_end:
        days_left = best_end - days
        return {
            "stage": "peak",
            "label":    "最佳期",
            "label_en": "Peak",
            "message":    f"当前处于最佳赏味窗口，还有 {days_left} 天",
            "message_en": f"Peak window — {days_left} day(s) remaining",
            "days_remaining": days_left,
            "is_stable": True,
        }
    else:
        over_days = days - best_end
        return {
            "stage": "declining",
            "label":    "衰退期",
            "label_en": "Declining",
            "message":    f"已过最佳期 {over_days} 天，建议调细补偿",
            "message_en": f"Past peak by {over_days} day(s) — grind finer to compensate",
            "days_remaining": -over_days,
            "is_stable": True,
        }


def is_resting_period(days: int, process_method: str) -> bool:
    w = FLAVOR_WINDOWS.get(process_method, FLAVOR_WINDOWS["washed"])
    return days < w["open"]


def freshness_delta(days_today: int, days_last: int, H: float = 1.0, D: float = 1.0) -> float:
    """
    今日 vs 上次 session 的新鲜度增量，用于每日刻度微调。

    规则：
    - 如果任意一方处于养豆期（≤7天），delta=0。
      养豆期的 resting_offset 描述的是参数不稳定性，不是方向性信号，
      跨越养豆期/老化期边界时差值会产生假跳跃，应忽略。
    - 两次都在老化期时，才返回真实增量（通常是很小的正数）。
    """
    if days_today <= RESTING_DAYS or days_last <= RESTING_DAYS:
        return 0.0
    return round(
        freshness_offset(days_today, H=H, D=D) - freshness_offset(days_last, H=H, D=D),
        4,
    )
