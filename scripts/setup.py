"""
初始化：建磨豆机档案 + 豆子档案
约束：磨豆机 ≤ 2台，豆子 ≤ 3款
"""

import json
import os
from datetime import date

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
GRINDERS_DIR = os.path.join(DATA_DIR, "grinders")
BEANS_DIR = os.path.join(DATA_DIR, "beans")

PROCESS_DENSITY = {
    "washed":    1.0,
    "natural":   0.9,
    "honey":     0.95,
    "anaerobic": 1.1,
}

ROAST_HARDNESS = {
    "light":        1.2,
    "medium_light": 1.1,
    "medium":       1.0,
    "medium_dark":  0.85,
    "dark":         0.7,
}

# ⚠ 实验性：各处理法和烘焙度的预期风味基线（-1 偏酸/亮，0 平衡，+1 偏苦/厚）
# 用于在解读用户味觉反馈时扣除豆子本身的风格特征，避免把天然的明亮/甜感当成萃取不足
PROCESS_FLAVOR_BASELINE = {
    "washed":    0.0,    # 干净中性，无额外预期
    "natural":  -0.15,   # 天然果香/甜感，预期偏亮
    "honey":    -0.08,   # 介于两者之间
    "anaerobic":-0.12,   # 发酵风味，预期偏复杂/略亮
}

ROAST_FLAVOR_BASELINE = {
    "light":        -0.2,   # 偏酸/花香，预期明亮
    "medium_light": -0.1,
    "medium":        0.0,   # 平衡基准
    "medium_dark":   0.1,
    "dark":          0.2,   # 偏苦/焦糖，预期厚重
}

MAX_GRINDERS = 2
MAX_BEANS = 3
BURR_WEAR_THRESHOLD_KG = 1000


def _list_profiles(directory: str) -> list[str]:
    if not os.path.exists(directory):
        return []
    return [f.replace(".json", "") for f in os.listdir(directory) if f.endswith(".json")]


def validate_capacity(grinder: bool = False, bean: bool = False) -> None:
    """超出容量时抛出异常，拒绝新建"""
    if grinder:
        existing = _list_profiles(GRINDERS_DIR)
        if len(existing) >= MAX_GRINDERS:
            raise ValueError(
                f"已达磨豆机上限（{MAX_GRINDERS} 台）。"
                f"当前：{existing}。请先删除一台再新建。"
            )
    if bean:
        existing = _list_profiles(BEANS_DIR)
        if len(existing) >= MAX_BEANS:
            raise ValueError(
                f"已达豆子上限（{MAX_BEANS} 款）。"
                f"当前：{existing}。请先删除一款再新建。"
            )


def create_grinder_profile(name: str, burr_type: str) -> dict:
    """
    新建磨豆机档案。
    burr_type: "flat" / "conical" / "burr"
    """
    validate_capacity(grinder=True)

    profile = {
        "name": name,
        "burr_type": burr_type,
        "beta": None,          # β 系数，需运行 calibrate.py 后写入
        "total_kg": 0.0,
        "calibrated_at": None,
        "wear_alert_at_kg": BURR_WEAR_THRESHOLD_KG,
    }

    path = os.path.join(GRINDERS_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    print(f"✓ 磨豆机档案已创建：{path}")
    print(f"  下一步：运行 calibrate.py --grinder \"{name}\" 完成 β 系数校准")
    return profile


def create_bean_profile(
    name: str,
    origin: str,
    process: str,
    roast_level: str,
    roast_date: str,
    dose_g: float,
    yield_g: float,
    target_time_s: int,
) -> dict:
    """
    新建豆子档案。
    process: "washed" / "natural" / "honey" / "anaerobic"
    roast_level: "light" / "medium_light" / "medium" / "medium_dark" / "dark"
    roast_date: "YYYY-MM-DD"
    """
    validate_capacity(bean=True)

    if process not in PROCESS_DENSITY:
        raise ValueError(f"未知处理法：{process}。可选：{list(PROCESS_DENSITY.keys())}")
    if roast_level not in ROAST_HARDNESS:
        raise ValueError(f"未知烘焙度：{roast_level}。可选：{list(ROAST_HARDNESS.keys())}")

    H = ROAST_HARDNESS[roast_level]
    D = PROCESS_DENSITY[process]
    # ⚠ 实验性：处理法 + 烘焙度共同决定预期风味基线
    flavor_baseline = round(
        PROCESS_FLAVOR_BASELINE[process] + ROAST_FLAVOR_BASELINE[roast_level], 3
    )

    profile = {
        "name": name,
        "origin": origin,
        "process": process,
        "roast_level": roast_level,
        "H": H,
        "D": D,
        "flavor_baseline": flavor_baseline,   # ⚠ 实验性，季度报告后自动校正
        "roast_date": roast_date,
        "dose_g": dose_g,
        "yield_g": yield_g,
        "target_time_s": target_time_s,
    }

    path = os.path.join(BEANS_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    print(f"✓ 豆子档案已创建：{path}")
    print(f"  H={H}（烘焙硬度）  D={D}（处理法密度）  flavor_baseline={flavor_baseline}  ⚠ 实验性参数")
    return profile


def load_grinder(name: str) -> dict:
    path = os.path.join(GRINDERS_DIR, f"{name}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到磨豆机档案：{name}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_grinder(profile: dict) -> None:
    name = profile["name"]
    path = os.path.join(GRINDERS_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def load_bean(name: str) -> dict:
    path = os.path.join(BEANS_DIR, f"{name}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到豆子档案：{name}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_bean(profile: dict) -> None:
    path = os.path.join(BEANS_DIR, f"{profile['name']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def check_burr_wear(grinder_name: str) -> None:
    """累计使用量达到阈值时提示复检"""
    profile = load_grinder(grinder_name)
    threshold = profile.get("wear_alert_at_kg", BURR_WEAR_THRESHOLD_KG)
    total = profile.get("total_kg", 0)
    if total >= threshold:
        next_threshold = (total // threshold + 1) * threshold
        print(
            f"⚠️  [{grinder_name}] 刀盘累计使用量已达 {total:.1f} kg（阈值 {threshold} kg）。"
            f"建议重新运行 β 系数校准。"
        )


def add_bean_kg(grinder_name: str, kg: float) -> None:
    """记录磨豆量，用于刀盘磨损追踪"""
    profile = load_grinder(grinder_name)
    profile["total_kg"] = round(profile.get("total_kg", 0) + kg, 3)
    save_grinder(profile)
    check_burr_wear(grinder_name)


def list_active_combinations() -> list[dict]:
    """列出所有可用的磨豆机 × 豆子组合"""
    grinders = _list_profiles(GRINDERS_DIR)
    beans = _list_profiles(BEANS_DIR)
    combos = []
    for g in grinders:
        for b in beans:
            combos.append({"grinder": g, "bean": b})
    return combos


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Coffee Agent 初始化工具")
    subparsers = parser.add_subparsers(dest="cmd")

    # 新建磨豆机
    pg = subparsers.add_parser("grinder", help="新建磨豆机档案")
    pg.add_argument("name")
    pg.add_argument("--burr", default="flat", help="刀盘类型: flat/conical")

    # 新建豆子
    pb = subparsers.add_parser("bean", help="新建豆子档案")
    pb.add_argument("name")
    pb.add_argument("--origin", required=True)
    pb.add_argument("--process", required=True, choices=list(PROCESS_DENSITY.keys()))
    pb.add_argument("--roast-level", required=True, help="light/medium-light/medium/medium-dark/dark")
    pb.add_argument("--roast-date", required=True)
    pb.add_argument("--dose", type=float, required=True)
    pb.add_argument("--yield-g", type=float, required=True)
    pb.add_argument("--target-time", type=int, required=True)

    # 列出组合
    subparsers.add_parser("list", help="列出当前档案")

    args = parser.parse_args()

    if args.cmd == "grinder":
        create_grinder_profile(args.name, args.burr)
    elif args.cmd == "bean":
        roast_level = args.roast_level.replace("-", "_")
        create_bean_profile(
            args.name, args.origin, args.process, roast_level,
            args.roast_date, args.dose, args.yield_g, args.target_time
        )
    elif args.cmd == "list":
        combos = list_active_combinations()
        print(f"磨豆机：{_list_profiles(GRINDERS_DIR)}")
        print(f"豆子：{_list_profiles(BEANS_DIR)}")
        print(f"可用组合：{len(combos)} 个")
    else:
        parser.print_help()
