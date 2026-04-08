"""
萃取率计算（可选，需要折射仪）
EY% = (TDS% × yield_g) / dose_g × 100
"""


def calc_ey(tds_pct: float, yield_g: float, dose_g: float) -> float:
    """
    计算萃取率 EY%。
    tds_pct: 折射仪读数（%，如 9.5）
    yield_g: 液重（克）
    dose_g: 粉量（克）
    """
    if dose_g <= 0:
        raise ValueError("粉量必须大于 0")
    ey = (tds_pct * yield_g) / dose_g
    return round(ey, 2)


def ey_assessment(ey_pct: float) -> str:
    """EY% 区间评估（参考 SCA 标准）"""
    if ey_pct < 18:
        return "萃取不足"
    elif ey_pct <= 22:
        return "萃取正常"
    else:
        return "过度萃取"
