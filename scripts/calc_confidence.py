"""
置信度计算
"""


def calc_confidence(
    recent_n: int,
    warm_flags: int = 0,
    missing_env_data: bool = False,
    has_data_gaps: bool = False,
) -> int:
    """
    返回置信度百分比（0-100）。

    参数：
        recent_n: 最近有效反馈数量
        warm_flags: recent_n 中 WARM 标记的数量
        missing_env_data: 温湿度是否使用估算值
        has_data_gaps: 数据是否有断层（>3天未记录）
    """
    # 基础分：由反馈数量决定，满分 70
    if recent_n == 0:
        base = 20
    elif recent_n < 5:
        base = 30 + recent_n * 4
    elif recent_n < 10:
        base = 50 + (recent_n - 5) * 3
    else:
        base = min(70, 65 + (recent_n - 10) // 5)

    # WARM 占比惩罚（最多 -20）
    if recent_n > 0:
        warm_ratio = warm_flags / recent_n
        warm_penalty = int(warm_ratio * 20)
    else:
        warm_penalty = 0

    # 环境数据估算惩罚
    env_penalty = 10 if missing_env_data else 0

    # 数据断层惩罚
    gap_penalty = 5 if has_data_gaps else 0

    confidence = base - warm_penalty - env_penalty - gap_penalty
    return max(10, min(100, confidence))


def detect_warm_patterns(warm_history: list[bool], window: int = 30) -> dict:
    """
    分析近 window 天的 WARM 记录。
    warm_history: 按时间顺序排列的布尔列表（True = WARM）
    """
    recent = warm_history[-window:] if len(warm_history) > window else warm_history
    if not recent:
        return {"frequency": 0.0, "alert": False, "message": ""}

    frequency = sum(recent) / len(recent)
    alert = frequency > 0.3

    message = ""
    if alert:
        pct = int(frequency * 100)
        message = (
            f"近 {len(recent)} 天 WARM 频率为 {pct}%（超过 30%），"
            f"感官数据权重已自动降低。建议关注身体状态规律。"
        )

    return {
        "frequency": round(frequency, 3),
        "alert": alert,
        "message": message,
    }
