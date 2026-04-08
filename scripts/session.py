"""
Daily session — split into two non-interactive commands:

  session.py recommend   — calculate and print today's grind recommendation
  session.py log         — save shot data after the user has pulled the shot

Agent collects all data conversationally, then calls each command once with full arguments.
No input() anywhere — all data comes from CLI arguments.
"""

import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))

from setup import load_grinder, load_bean, save_grinder, add_bean_kg
from calc_freshness import days_since_roast, freshness_offset, freshness_delta, flavor_stage
from calc_grind import calc_grind_offset, suggested_setting, offset_breakdown, extreme_env_warning
from calc_confidence import calc_confidence, detect_warm_patterns
from vocab import load_vocab, parse_taste_input, update_vocab
from output import (
    format_recommendation, format_warm_recommendation,
    format_stage_warning, format_anomaly_report,
    format_bootstrap_warning, format_purge_notice,
)
from gen_report import get_table_suggestion, check_quarterly_report, generate_report

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
ANOMALIES_DIR = os.path.join(DATA_DIR, "anomalies")

FLOW_DEVIATION_THRESHOLD = 3.0
ANOMALY_PATTERN_THRESHOLD = 5
# PURGE_THRESHOLD is read per-grinder from grinder["step_size"] — not hardcoded here


# ── Helpers ────────────────────────────────────────────────

def get_learning_phase(shot_count: int) -> str:
    if shot_count < 10:
        return "bootstrap"
    elif shot_count < 50:
        return "growing"
    return "mature"


def count_total_shots(grinder: str, bean: str) -> int:
    total = 0
    if not os.path.exists(SESSIONS_DIR):
        return 0
    for fname in os.listdir(SESSIONS_DIR):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(SESSIONS_DIR, fname), encoding="utf-8") as f:
            sess = json.load(f)
        if sess.get("grinder") == grinder and sess.get("bean") == bean:
            for shot in sess.get("shots", []):
                if shot.get("type") != "purge" and not shot.get("technique_error"):
                    total += 1
    return total


def _load_last_session(grinder: str, bean: str) -> dict | None:
    if not os.path.exists(SESSIONS_DIR):
        return None
    sessions = sorted(f for f in os.listdir(SESSIONS_DIR) if f.endswith(".json"))
    for fname in reversed(sessions):
        with open(os.path.join(SESSIONS_DIR, fname), encoding="utf-8") as f:
            sess = json.load(f)
        if sess.get("grinder") == grinder and sess.get("bean") == bean:
            return sess
    return None


def _get_last_setting(grinder: str, bean: str, default: float = 2.5) -> float:
    sess = _load_last_session(grinder, bean)
    if sess and sess.get("shots"):
        for shot in reversed(sess["shots"]):
            if shot.get("type") != "purge":
                return shot.get("setting", default)
    return default


def _get_last_flow(grinder: str, bean: str, current_suggested: float, step_size: float) -> float | None:
    """Return last session's flow time only if setting hasn't changed by >= step_size."""
    sess = _load_last_session(grinder, bean)
    if not sess or not sess.get("shots"):
        return None
    for shot in sess["shots"]:
        if shot.get("type") not in ("purge",) and not shot.get("technique_error"):
            last_used_setting = shot.get("setting", 0)
            if abs(last_used_setting - current_suggested) < step_size:
                return shot.get("flow_time")
            return None
    return None


def _get_warm_history(grinder: str, bean: str, window: int = 30) -> list:
    history = []
    if not os.path.exists(SESSIONS_DIR):
        return history
    sessions = sorted(f for f in os.listdir(SESSIONS_DIR) if f.endswith(".json"))[-window:]
    for fname in sessions:
        with open(os.path.join(SESSIONS_DIR, fname), encoding="utf-8") as f:
            sess = json.load(f)
        if sess.get("grinder") == grinder and sess.get("bean") == bean:
            history.append(sess.get("warm_state") == "warm")
    return history


def _save_session(session_data: dict) -> None:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    today = date.today().isoformat()
    path = os.path.join(SESSIONS_DIR, f"{today}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)


def log_anomaly(shot_data: dict, bean_id: str) -> None:
    os.makedirs(ANOMALIES_DIR, exist_ok=True)
    path = os.path.join(ANOMALIES_DIR, f"{bean_id}.json")
    records = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            records = json.load(f)
    records.append(shot_data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def check_anomaly_pattern(bean_id: str) -> list:
    path = os.path.join(ANOMALIES_DIR, f"{bean_id}.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    if len(records) < ANOMALY_PATTERN_THRESHOLD:
        return []
    patterns = []
    sensory = [r for r in records if r.get("flow_normal") and r.get("taste") != 0]
    if len(sensory) >= 3:
        avg = sum(r.get("taste", 0) for r in sensory) / len(sensory)
        direction = "sour" if avg < 0 else "bitter"
        patterns.append(
            f"Flow on-target but taste consistently {direction} ({len(sensory)} times) — consider ratio adjustment"
        )
    days_list = [r.get("days_since_roast", 0) for r in records]
    if days_list:
        patterns.append(f"Anomalies cluster around day {int(sum(days_list)/len(days_list))} post-roast")
    return patterns


def detect_communication_style(response: str) -> str:
    variable_patterns = [
        r"\d+\.?\d*\s*(g|s|°C|°F|%|clicks?|steps?|notches?)",
        r"[0-9]+:[0-9]+",
        r"\b(setting|grind|dose|yield|temp|humidity|time|ratio|flow)\b",
    ]
    var_count = sum(len(re.findall(p, response, re.IGNORECASE)) for p in variable_patterns)
    word_count = len(response.split())
    if var_count >= 3 and word_count < 60:
        return "verbose"
    elif word_count < 25:
        return "qa"
    return "freeform"


# ── recommend ──────────────────────────────────────────────

def cmd_recommend(args) -> None:
    """
    Calculate and print today's grind recommendation.
    Called BEFORE the user pulls any shots.

    Required: --grinder --bean --temp --humidity --warm
    """
    grinder = load_grinder(args.grinder)
    bean = load_bean(args.bean)

    if grinder["beta"] is None:
        print(f"ERROR: [{args.grinder}] β not calibrated. Run calibrate.py first.")
        sys.exit(1)

    warm_state = args.warm  # "normal" | "warm"
    temp = args.temp
    humidity = args.humidity
    env_estimated = args.env_estimated

    days = days_since_roast(bean["roast_date"])
    stage = flavor_stage(days, bean["process"])
    H = bean.get("H", 1.0)
    D = bean.get("D", 1.0)
    step_size = grinder.get("step_size", 0.5)

    # 个人公式系数（季度报告回归后写入 bean 档案，优先于经验估算值）
    pf = bean.get("personal_formula")
    personal_temp_coeff     = pf["temp_coeff"]     if pf else None
    personal_humidity_coeff = pf["humidity_coeff"] if pf else None

    last_sess = _load_last_session(args.grinder, args.bean)
    is_first_session = last_sess is None

    # All corrections are DELTAS vs last session — prevents cumulative drift.
    last_days = last_sess["days_since_roast"] if last_sess else days
    last_temp = last_sess["temp"] if last_sess else temp          # delta=0 on first session
    last_humidity = last_sess["humidity"] if last_sess else humidity

    f_offset = freshness_delta(days, last_days, H=H, D=D)
    temp_delta = temp - last_temp
    humidity_delta = humidity - last_humidity

    # Seasonal lookup table as warm-start baseline (only when we already have history)
    table_setting = get_table_suggestion(args.grinder, args.bean, temp, humidity)
    last_setting = _get_last_setting(args.grinder, args.bean)

    # First session: no history to anchor from — don't calculate, ask user for current setting
    if is_first_session and table_setting is None:
        print("FIRST_SESSION=true")
        print("No previous session data. Cannot calculate a recommendation without an anchor setting.")
        print("Ask the user: what grind setting are you currently using? Log that with session.py log, then tomorrow a real recommendation will be available.")
        return

    if table_setting is not None and is_first_session:
        print(f"→ Seasonal table suggests {table_setting} for {temp}°C / {humidity}% — using as baseline.")
        last_setting = table_setting

    # Two-pass: detect setting change before using last flow
    grind_offset_no_flow = calc_grind_offset(
        beta=grinder["beta"], freshness_offset=f_offset,
        temp_delta=temp_delta, humidity_delta=humidity_delta, flow_deviation=0.0,
        temp_coeff=personal_temp_coeff, humidity_coeff=personal_humidity_coeff,
    )
    suggested_no_flow = suggested_setting(last_setting, grind_offset_no_flow, step_size)

    last_flow = _get_last_flow(args.grinder, args.bean, suggested_no_flow, step_size)
    flow_deviation = (last_flow - bean["target_time_s"]) if last_flow is not None else 0.0

    if warm_state == "warm":
        beta = grinder["beta"]
        grind_offset = (-flow_deviation / beta) if beta != 0 else 0.0
    else:
        grind_offset = calc_grind_offset(
            beta=grinder["beta"], freshness_offset=f_offset,
            temp_delta=temp_delta, humidity_delta=humidity_delta,
            flow_deviation=flow_deviation,
            temp_coeff=personal_temp_coeff, humidity_coeff=personal_humidity_coeff,
        )

    suggested = suggested_setting(last_setting, grind_offset, step_size)
    factors = offset_breakdown(
        grinder["beta"], f_offset,
        temp_delta=temp_delta, humidity_delta=humidity_delta,
        flow_deviation=flow_deviation,
        temp_coeff=personal_temp_coeff, humidity_coeff=personal_humidity_coeff,
    )

    shot_count = count_total_shots(args.grinder, args.bean)
    warm_history = _get_warm_history(args.grinder, args.bean)
    confidence = calc_confidence(
        recent_n=min(shot_count, 20),
        warm_flags=sum(warm_history[-10:]),
        missing_env_data=env_estimated,
    )

    lang = args.lang
    print()
    if warm_state == "warm":
        print(format_warm_recommendation(suggested, last_setting, lang=lang))
    else:
        print(format_recommendation(
            grinder=args.grinder, bean=args.bean, origin=bean["origin"],
            days=days, stage=stage, last_setting=last_setting,
            suggested=suggested, target_time_s=bean["target_time_s"],
            confidence=confidence, recent_n=min(shot_count, 20),
            factors=factors, env_estimated=env_estimated, lang=lang,
            personal_formula=bean.get("personal_formula"),
        ))

    if shot_count < 10:
        print(format_bootstrap_warning(shot_count, confidence, lang=lang))

    stage_warn = format_stage_warning(stage, lang=lang)
    if stage_warn:
        print(stage_warn)

    env_warn = extreme_env_warning(temp_delta, humidity_delta)
    if env_warn:
        print(env_warn)

    # Purge shot notice — only when setting actually changed from a real previous session
    # Skip on first session: there's no residual grounds from a prior grind
    if not is_first_session and abs(last_setting - suggested) >= step_size:
        print()
        print(format_purge_notice(last_setting, suggested, lang=lang))
        print("PURGE_REQUIRED=true")
    else:
        print("PURGE_REQUIRED=false")

    # Print suggested setting on its own line so agent can parse it
    print(f"SUGGESTED_SETTING={suggested}")


# ── log ────────────────────────────────────────────────────

def cmd_log(args) -> None:
    """
    Save shot data after the user has pulled the shot(s).
    Agent calls this once per session with all collected data.

    Required: --grinder --bean --temp --humidity --warm
              --setting --flow-time
    Optional: --taste --technique-error --intentional
              --purge-flow (if purge shot was pulled)
    """
    grinder = load_grinder(args.grinder)
    bean = load_bean(args.bean)
    vocab = load_vocab()

    warm_state = args.warm
    temp = args.temp
    humidity = args.humidity
    setting = args.setting
    flow_time = args.flow_time
    taste_raw = args.taste or ""
    technique_error = args.technique_error
    intentional = args.intentional
    env_estimated = args.env_estimated

    days = days_since_roast(bean["roast_date"])
    shots = []

    # Purge shot
    if args.purge_flow is not None:
        shots.append({
            "type": "purge",
            "setting": setting,
            "flow_time": args.purge_flow,
            "taste": None,
            "warm_weight": 1.0,
            "anomaly": False,
            "intentional": False,
            "technique_error": False,
        })
        print("✓ Purge shot logged. Excluded from model.")

    # Parse taste
    # 词典学习和 WARM 判断是两件独立的事：
    # 无论今天是否 WARM，都解析味觉词，收录未知词，建立词汇风格库。
    # WARM 只影响 taste_score 是否写入模型，不阻止词汇学习。
    taste_score = None
    if taste_raw:
        parsed = parse_taste_input(taste_raw, vocab)

        # WARM_flag 词触发状态切换（优先级最高）
        if parsed["warm_flag"] and warm_state != "warm":
            warm_state = "warm"
            print("WARM word detected. Switching to WARM mode.")

        # 未知词：通知 agent 去收录（无论是否 WARM）
        for unk in parsed["unknown_words"]:
            print(f"UNKNOWN_WORD: {unk}")

        # 分数只在 normal 模式下写入
        if warm_state != "warm" and parsed["score"] is not None:
            taste_score = round(parsed["score"], 3)

    # ⚠ 实验性：用 flavor_baseline 修正味觉判断
    # 扣除豆子本身的风格预期后，剩余偏差才视为萃取问题
    # 例：日晒豆天然偏亮（baseline=-0.15），用户说"明亮"时 adjusted≈0，不触发调整
    flavor_baseline = bean.get("flavor_baseline", 0.0)
    if taste_score is not None:
        taste_adjusted = round(taste_score - flavor_baseline, 3)
    else:
        taste_adjusted = None

    flow_deviation_actual = flow_time - bean["target_time_s"]
    is_anomaly = (
        (abs(flow_deviation_actual) > FLOW_DEVIATION_THRESHOLD or
         (taste_adjusted is not None and abs(taste_adjusted) > 0.15))  # 允许 baseline 误差容忍带
        and not technique_error
        and not intentional
    )

    shot = {
        "type": "dial",
        "setting": setting,
        "flow_time": flow_time,
        "taste": taste_score,           # 原始味觉分数
        "taste_adjusted": taste_adjusted,  # 扣除 flavor_baseline 后的偏差（⚠ 实验性）
        "warm_weight": 0.2 if warm_state == "warm" else 1.0,
        "anomaly": is_anomaly,
        "intentional": intentional,
        "technique_error": technique_error,
    }
    shots.append(shot)

    # Anomaly log
    if is_anomaly and warm_state != "warm":
        log_anomaly({
            "date": date.today().isoformat(),
            "setting": setting,
            "flow_time": flow_time,
            "taste": taste_score,
            "flow_normal": abs(flow_deviation_actual) <= FLOW_DEVIATION_THRESHOLD,
            "days_since_roast": days,
        }, args.bean)
        patterns = check_anomaly_pattern(args.bean)
        if patterns:
            print()
            print(format_anomaly_report(args.bean, len(patterns) + ANOMALY_PATTERN_THRESHOLD - 1, patterns))

    # Save session
    shot_count = count_total_shots(args.grinder, args.bean)
    confidence = calc_confidence(
        recent_n=min(shot_count, 20),
        warm_flags=sum(_get_warm_history(args.grinder, args.bean)[-10:]),
        missing_env_data=env_estimated,
    )
    last_setting = _get_last_setting(args.grinder, args.bean)

    session_data = {
        "date": date.today().isoformat(),
        "grinder": args.grinder,
        "bean": args.bean,
        "days_since_roast": days,
        "temp": temp,
        "humidity": humidity,
        "env_source": "estimated" if env_estimated else "manual",
        "warm_state": warm_state,
        "shots": shots,
        "recommendation": {
            "adjustment": round(setting - last_setting, 2),
            "confidence": confidence,
        },
    }
    _save_session(session_data)

    real_shots = [s for s in shots if s.get("type") != "purge"]
    add_bean_kg(args.grinder, len(real_shots) * bean.get("dose_g", 18) / 1000)

    new_count = shot_count + len(real_shots)
    if shot_count < 10 <= new_count:
        print("\n→ 10 shots reached. Model is starting to personalise.")
    elif shot_count < 50 <= new_count:
        print("\n→ 50 shots reached. Mature phase.")

    if check_quarterly_report(args.grinder, args.bean, new_count):
        print(f"\n── Quarterly report available ({new_count} shots this quarter) ──")
        print("Run: python3 scripts/gen_report.py to generate.")

    print("\n✓ Session saved.")


# ── CLI ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Coffee Dialing Agent — Daily Session")
    sub = parser.add_subparsers(dest="cmd")

    # ── recommend ──
    rec = sub.add_parser("recommend", help="Calculate today's grind recommendation")
    rec.add_argument("--grinder", required=True)
    rec.add_argument("--bean", required=True)
    rec.add_argument("--temp", type=float, required=True, help="Temperature °C")
    rec.add_argument("--humidity", type=float, required=True, help="Humidity %%")
    rec.add_argument("--warm", choices=["normal", "warm"], default="normal")
    rec.add_argument("--env-estimated", action="store_true",
                     help="Flag if env data is estimated (reduces confidence)")
    rec.add_argument("--lang", choices=["zh", "en"], default="zh",
                     help="Output language (zh=Chinese, en=English)")

    # ── log ──
    lg = sub.add_parser("log", help="Save shot data after pulling")
    lg.add_argument("--grinder", required=True)
    lg.add_argument("--bean", required=True)
    lg.add_argument("--temp", type=float, required=True)
    lg.add_argument("--humidity", type=float, required=True)
    lg.add_argument("--warm", choices=["normal", "warm"], default="normal")
    lg.add_argument("--setting", type=float, required=True, help="Setting actually used")
    lg.add_argument("--flow-time", type=float, required=True, help="Actual shot time (seconds)")
    lg.add_argument("--taste", default="", help="Taste notes, comma-separated")
    lg.add_argument("--technique-error", action="store_true")
    lg.add_argument("--intentional", action="store_true")
    lg.add_argument("--purge-flow", type=float, default=None,
                    help="Purge shot time if a purge was pulled")
    lg.add_argument("--env-estimated", action="store_true")
    lg.add_argument("--lang", choices=["zh", "en"], default="zh",
                     help="Output language (zh=Chinese, en=English)")

    args = parser.parse_args()

    if args.cmd == "recommend":
        cmd_recommend(args)
    elif args.cmd == "log":
        cmd_log(args)
    else:
        parser.print_help()
