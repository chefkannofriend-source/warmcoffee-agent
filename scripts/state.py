"""
会话状态存档 — 跨对话记忆
记录当前所处阶段，让 Agent 在新对话中能恢复上下文。
"""

import json
import os
from datetime import date

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

# 合法阶段值
PHASES = ("cold_start", "session")


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def set_cold_start(grinder: str, bean: str, day: int, step_size: float,
                   recommend_timing: str = None) -> None:
    """记录冷启动进度"""
    state = load_state()
    key = f"{grinder}::{bean}"
    state[key] = {
        "phase": "cold_start",
        "cold_start_day": day,
        "step_size": step_size,
        "recommend_timing": recommend_timing,  # "before" | "after" | None
        "updated": date.today().isoformat(),
    }
    save_state(state)


def set_session_phase(grinder: str, bean: str, recommend_timing: str,
                      step_size: float) -> None:
    """冷启动结束，切换到正式 session 阶段"""
    state = load_state()
    key = f"{grinder}::{bean}"
    state[key] = {
        "phase": "session",
        "recommend_timing": recommend_timing,
        "step_size": step_size,
        "updated": date.today().isoformat(),
    }
    save_state(state)


def get_combo_state(grinder: str, bean: str) -> dict:
    """读取某磨豆机×豆子组合的状态，不存在返回空 dict"""
    state = load_state()
    return state.get(f"{grinder}::{bean}", {})


def print_status() -> None:
    """打印所有组合的当前状态（供 Agent 启动时读取）"""
    state = load_state()
    if not state:
        print("无状态记录（全新安装或数据已清除）")
        return
    for key, info in state.items():
        grinder, bean = key.split("::")
        phase = info.get("phase", "unknown")
        updated = info.get("updated", "?")
        if phase == "cold_start":
            day = info.get("cold_start_day", "?")
            step = info.get("step_size", "?")
            timing = info.get("recommend_timing") or "未设置"
            print(f"[{grinder} × {bean}]  冷启动 Day {day}/3  步长={step}  "
                  f"建议时机={timing}  最后更新={updated}")
        elif phase == "session":
            step = info.get("step_size", "?")
            timing = info.get("recommend_timing", "?")
            print(f"[{grinder} × {bean}]  正式 session  步长={step}  "
                  f"建议时机={timing}  最后更新={updated}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="读取/更新会话状态")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="打印当前所有状态")

    sp = sub.add_parser("cold-start", help="更新冷启动进度")
    sp.add_argument("--grinder", required=True)
    sp.add_argument("--bean", required=True)
    sp.add_argument("--day", type=int, required=True)
    sp.add_argument("--step-size", type=float, required=True)
    sp.add_argument("--timing", default=None, help="before / after")

    ss = sub.add_parser("session", help="切换到正式 session 阶段")
    ss.add_argument("--grinder", required=True)
    ss.add_argument("--bean", required=True)
    ss.add_argument("--timing", required=True, help="before / after")
    ss.add_argument("--step-size", type=float, required=True)

    args = parser.parse_args()

    if args.cmd == "status":
        print_status()
    elif args.cmd == "cold-start":
        set_cold_start(args.grinder, args.bean, args.day,
                       args.step_size, args.timing)
        print(f"✓ 已记录冷启动 Day {args.day}")
    elif args.cmd == "session":
        set_session_phase(args.grinder, args.bean, args.timing, args.step_size)
        print("✓ 已切换到正式 session 阶段")
    else:
        parser.print_help()
