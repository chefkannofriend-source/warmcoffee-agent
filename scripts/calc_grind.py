"""
综合研磨偏移量计算

  grind_offset = β × freshness_delta   ← freshness 是 β-normalized 量，需要 β 转换成格数
               + temp_correction        ← 今日 vs 上次温度增量 → 格数，直接叠加
               + humidity_correction    ← 今日 vs 上次湿度增量 → 格数，直接叠加
               + flow_correction        ← 上次流速偏差 → 格数，直接叠加

所有参数传的都是增量（delta），不是绝对值。
这样相同条件下 offset=0，只有条件变化时才触发调整。

⚠ 线性近似的适用范围：
  TEMP_COEFFICIENT 和 HUMIDITY_COEFFICIENT 是经验估算，假设线性关系。
  适用范围大约：温度 10–35°C，湿度 30–95%。
  超出此范围（极寒、极干）线性系数失效，模型可信度下降。
  季度个人公式会用实测数据替换这两个估算系数。
"""

# ⚠ 线性估算系数，适用范围约 10–35°C / 30–95% RH
TEMP_COEFFICIENT = 0.05       # 每 1°C 变化 → 0.05 格（10°C 变化 ≈ 0.5 格）
HUMIDITY_COEFFICIENT = 0.01   # 每 1% 湿度变化 → 0.01 格
# flow correction: -deviation / beta（直接用 β 换算，无需固定系数）

# 极端条件阈值 — 超出时输出警告
TEMP_EXTREME_DELTA = 15.0     # 单次 session 温差超过此值视为极端
HUMIDITY_EXTREME_DELTA = 40.0 # 单次 session 湿差超过此值视为极端


def extreme_env_warning(temp_delta: float, humidity_delta: float) -> str | None:
    """
    条件变化幅度超出线性模型适用范围时返回警告文字，否则返回 None。
    调用方决定是否展示给用户。
    """
    warnings = []
    if abs(temp_delta) >= TEMP_EXTREME_DELTA:
        warnings.append(
            f"⚠ Temperature shifted {temp_delta:+.1f}°C since last session — "
            f"linear model may underestimate the correction needed. "
            f"Trust your taste over the number today."
        )
    if abs(humidity_delta) >= HUMIDITY_EXTREME_DELTA:
        warnings.append(
            f"⚠ Humidity shifted {humidity_delta:+.1f}% since last session — "
            f"same caveat applies."
        )
    return "\n".join(warnings) if warnings else None


def calc_grind_offset(
    beta: float,
    freshness_offset: float,
    temp_delta: float = 0.0,
    humidity_delta: float = 0.0,
    flow_deviation: float = 0.0,
    temp_coeff: float | None = None,
    humidity_coeff: float | None = None,
) -> float:
    """
    计算综合研磨偏移量（格数）。每次调用传入的都是**增量**，不是绝对值。
    正值 = 调细，负值 = 调粗。

    参数：
        beta:             磨豆机响应斜率（格/秒）
        freshness_offset: freshness_delta 输出（已是格数，直接叠加，无需乘 β）
        temp_delta:       今日温度 - 上次温度（°C）
        humidity_delta:   今日湿度 - 上次湿度（%）
        flow_deviation:   昨日流速偏差（实际 - 目标，秒）

    freshness_offset 取负：豆子越老需要越细 → 负偏移量。
    flow correction = -deviation / beta：流速慢（正偏差）→ 调粗（对任何磨豆机方向均正确）。
    温度/湿度传增量，防止每次 session 从固定基准重复叠加同一个偏移量。
    """
    tc = temp_coeff     if temp_coeff     is not None else TEMP_COEFFICIENT
    hc = humidity_coeff if humidity_coeff is not None else HUMIDITY_COEFFICIENT
    temp_correction     = tc * temp_delta
    humidity_correction = hc * humidity_delta
    f_correction = (-flow_deviation / beta) if beta != 0 else 0.0

    offset = -freshness_offset + temp_correction + humidity_correction + f_correction
    return round(offset, 2)


def suggested_setting(last_setting: float, grind_offset: float, step_size: float = 0.5) -> float:
    """今日建议刻度 = 昨日刻度 + 偏移量，精度取 step_size（该磨豆机的最小有效调整单位）"""
    raw = last_setting + grind_offset
    # 四舍五入到最近 step_size 格
    rounded = round(raw / step_size) * step_size
    return round(rounded, 4)


def brew_ratio(yield_g: float, dose_g: float) -> float:
    """萃取比例 yield : dose"""
    if dose_g <= 0:
        raise ValueError("粉量必须大于 0")
    return round(yield_g / dose_g, 2)


def offset_breakdown(
    beta: float,
    freshness_offset: float,
    temp_delta: float = 0.0,
    humidity_delta: float = 0.0,
    flow_deviation: float = 0.0,
    temp_coeff: float | None = None,
    humidity_coeff: float | None = None,
) -> dict:
    """返回各项因素贡献的明细，用于输出「主要影响因素」（均为增量）"""
    tc = temp_coeff     if temp_coeff     is not None else TEMP_COEFFICIENT
    hc = humidity_coeff if humidity_coeff is not None else HUMIDITY_COEFFICIENT
    temp_correction     = tc * temp_delta
    humidity_correction = hc * humidity_delta
    f_correction = (-flow_deviation / beta) if beta != 0 else 0.0

    factors = {
        "freshness":    round(-freshness_offset, 3),  # 豆子越老越细，取负
        "temperature":  round(temp_correction, 3),
        "humidity":     round(humidity_correction, 3),
        "flow":         round(f_correction, 3),
    }

    # 按绝对值排序，最大影响因子排前面
    sorted_factors = sorted(factors.items(), key=lambda x: abs(x[1]), reverse=True)
    return dict(sorted_factors)
