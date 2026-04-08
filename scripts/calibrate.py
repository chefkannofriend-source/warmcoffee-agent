"""
β 系数校准
Agent 通过对话收集 3 杯数据后，一次性传入本脚本计算并写入磨豆机档案。

用法：
  python3 scripts/calibrate.py --grinder "ek43" \
      --settings "2.0,1.5,1.0" --times "24,27,30"   # 步长 0.5，适合细刻度磨豆机
  python3 scripts/calibrate.py --grinder "ek43" \
      --settings "8,6,4" --times "22,27,32"          # 步长 2，适合粗刻度磨豆机
"""

import json
import os
import argparse
from datetime import date

import sys
sys.path.insert(0, os.path.dirname(__file__))
from setup import load_grinder, save_grinder


def validate_monotonic(settings: list, flow_times: list) -> str | None:
    """
    检查校准数据单调性：刻度越细（数字越小）→ 流速越慢（时间越长）。
    返回 None 表示通过；返回错误描述字符串表示需要重测。
    """
    # 判断刻度方向：取第一段差值的符号
    setting_diffs = [settings[i+1] - settings[i] for i in range(len(settings)-1)]
    time_diffs    = [flow_times[i+1] - flow_times[i] for i in range(len(flow_times)-1)]

    # 刻度方向必须一致（全递增或全递减）
    if any(d == 0 for d in setting_diffs):
        return "有两杯刻度相同，无法计算响应斜率，请重测。"
    setting_dir = 1 if setting_diffs[0] > 0 else -1
    if any((d * setting_dir) <= 0 for d in setting_diffs):
        return "刻度值方向不一致，请按同一方向逐步调整后重测。"

    # 流速方向必须与刻度方向相反（越细越慢）
    # 即：setting 增大 → flow_time 减小，反之亦然
    for s_diff, t_diff in zip(setting_diffs, time_diffs):
        if s_diff * t_diff > 0:
            # 同向：刻度增大但流速也变长（或刻度减小但流速也变短）
            return (
                f"流速方向与刻度方向相同（刻度变化 {s_diff:+g}，流速变化 {t_diff:+g}s）。\n"
                "可能原因：出粉不均匀、布粉手法、或数据记录有误。\n"
                "建议：重新拉平，每杯间隔 30 秒等待，再重测 3 杯。"
            )
        if t_diff == 0:
            return (
                f"两杯流速完全相同（{flow_times}），刻度调整未产生效果。\n"
                "步长可能过小——试试更大的调整幅度后重测。"
            )
    return None


def fit_beta(settings: list, flow_times: list) -> float:
    """
    最小二乘拟合刻度-流速响应斜率 β。
    β = Δflow_time / Δsetting（每格对应的流速变化秒数）
    注：调细（刻度数字减小）→ 流速变长，β 通常为负值，公式内部处理符号。
    调用前应先通过 validate_monotonic() 确认数据质量。
    """
    if len(settings) != len(flow_times) or len(settings) < 2:
        raise ValueError("需要至少 2 个数据点")

    n = len(settings)
    sum_x = sum(settings)
    sum_y = sum(flow_times)
    sum_xy = sum(settings[i] * flow_times[i] for i in range(n))
    sum_xx = sum(s ** 2 for s in settings)

    denom = n * sum_xx - sum_x ** 2
    if abs(denom) < 1e-9:
        raise ValueError("刻度值无变化，无法拟合")

    beta = (n * sum_xy - sum_x * sum_y) / denom
    return round(beta, 4)


def run_calibration(grinder_name: str, settings: list, flow_times: list) -> float:
    """
    接收已收集好的 3 杯数据，拟合 β 并写入磨豆机档案。
    """
    profile = load_grinder(grinder_name)

    err = validate_monotonic(settings, flow_times)
    if err:
        print(f"\n⚠  校准数据有问题，β 未写入：\n{err}")
        sys.exit(1)

    beta = fit_beta(settings, flow_times)

    print(f"\n── 校准结果：{grinder_name} ──")
    for s, t in zip(settings, flow_times):
        print(f"  刻度 {s} → {t} 秒")
    print(f"拟合 β = {beta}（每调细 1 格，流速变化 {beta:.2f} 秒）")

    if abs(beta) < 0.5:
        print("⚠  β 绝对值偏小，刻度响应可能不明显，数据已写入但建议核查。")

    # 步长 = 校准时每杯的刻度间距，作为该磨豆机的最小有效调整单位
    step_size = round(abs(settings[0] - settings[1]), 4)

    profile["beta"] = beta
    profile["step_size"] = step_size   # 用于 purge 检测和建议精度
    profile["calibrated_at"] = date.today().isoformat()
    save_grinder(profile)
    print(f"✓ β 系数已写入档案：{grinder_name}.json")
    print(f"  步长（最小有效调整单位）：{step_size} 格")

    return beta


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="β 系数校准（非交互式）")
    parser.add_argument("--grinder", required=True, help="磨豆机名称")
    parser.add_argument(
        "--settings", required=True,
        help="3 杯刻度，逗号分隔，如 2.0,1.5,1.0"
    )
    parser.add_argument(
        "--times", required=True,
        help="3 杯萃取时间（秒），逗号分隔，如 24,27,30"
    )
    args = parser.parse_args()

    try:
        settings = [float(x.strip()) for x in args.settings.split(",")]
        times = [float(x.strip()) for x in args.times.split(",")]
    except ValueError:
        print("错误：--settings 和 --times 必须是逗号分隔的数字")
        sys.exit(1)

    if len(settings) != 3 or len(times) != 3:
        print("错误：必须提供恰好 3 个刻度和 3 个时间数据")
        sys.exit(1)

    run_calibration(args.grinder, settings, times)
