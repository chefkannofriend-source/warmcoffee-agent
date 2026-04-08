"""
Formatted output for recommendations and alerts.
All public functions accept lang="zh"|"en" and respond in that language.
"""

FACTOR_LABELS = {
    "zh": {
        "freshness":   "豆子新鲜度",
        "temperature": "温度",
        "humidity":    "湿度",
        "flow":        "上次流速",
    },
    "en": {
        "freshness":   "roast age",
        "temperature": "temperature",
        "humidity":    "humidity",
        "flow":        "last shot flow",
    },
}


def _label(stage: dict, lang: str) -> str:
    return stage.get("label_en" if lang == "en" else "label", stage.get("label", ""))


def _message(stage: dict, lang: str) -> str:
    return stage.get("message_en" if lang == "en" else "message", stage.get("message", ""))


def _formula_label(personal_formula: dict | None, lang: str) -> str:
    """One-line note shown in recommendation: which coefficients are active and their quality."""
    if personal_formula is None:
        return ("（使用行业估算系数，个人公式尚未生成）"
                if lang == "zh" else
                "(Using generic coefficients — personal formula not yet generated)")
    r2 = personal_formula.get("r2", 0)
    n  = personal_formula.get("n_shots", 0)
    if r2 >= 0.8:
        tag = "强" if lang == "zh" else "strong"
    elif r2 >= 0.6:
        tag = "中" if lang == "zh" else "moderate"
    elif r2 >= 0.4:
        tag = "弱" if lang == "zh" else "weak"
    else:
        tag = "较差" if lang == "zh" else "poor"
    if lang == "zh":
        return f"（使用个人公式  R²={r2} [{tag}拟合]，基于 {n} 杯数据）"
    return f"(Personal formula active  R²={r2} [{tag} fit], {n} shots)"


def format_recommendation(
    grinder: str,
    bean: str,
    origin: str,
    days: int,
    stage: dict,
    last_setting: float,
    suggested: float,
    target_time_s: int,
    confidence: int,
    recent_n: int,
    factors: dict,
    env_estimated: bool = False,
    lang: str = "zh",
    personal_formula: dict | None = None,
) -> str:
    adjustment = round(suggested - last_setting, 4)
    if adjustment > 0:
        direction = f"+{adjustment}"
    elif adjustment < 0:
        direction = str(adjustment)
    else:
        direction = "0"

    flow_low  = target_time_s - 3
    flow_high = target_time_s + 3
    labels = FACTOR_LABELS[lang]

    top_factors = [
        labels.get(k, k)
        for k, v in factors.items()
        if abs(v) > 0.01
    ][:2]

    formula_note = _formula_label(personal_formula, lang)

    if lang == "zh":
        factor_str = " · ".join(top_factors) if top_factors else "综合因素"
        env_note   = "\n⚠️  环境数据使用昨日估算值，置信度已降低" if env_estimated else ""
        lines = [
            "── 今日建议 ──",
            f"豆子：{origin}  ·  烘焙后第 {days} 天  [{_label(stage, lang)}]",
            f"磨豆机：{grinder}",
            "",
            f"研磨调整：{direction} 格",
            f"→ 昨日 {last_setting}  →  今日 {suggested}",
            "",
            f"预计第一杯：{flow_low}–{flow_high}s（目标 {target_time_s}s）",
            f"置信度：{confidence}%（基于近 {recent_n} 杯数据）",
            f"{formula_note}",
            "",
            f"主要影响因素：{factor_str}",
            env_note,
            "",
            "---",
            "冲完告诉我实际时间。",
        ]
    else:
        factor_str = " · ".join(top_factors) if top_factors else "combined factors"
        env_note   = "\n⚠️  Environment data estimated from yesterday — confidence reduced" if env_estimated else ""
        lines = [
            "── Today's recommendation ──",
            f"Bean:    {origin}  ·  Day {days} post-roast  [{_label(stage, lang)}]",
            f"Grinder: {grinder}",
            "",
            f"Grind adjustment: {direction} step(s)",
            f"→ Yesterday {last_setting}  →  Today {suggested}",
            "",
            f"Predicted first shot: {flow_low}–{flow_high}s  (target {target_time_s}s)",
            f"Confidence: {confidence}%  (based on last {recent_n} shots)",
            f"{formula_note}",
            "",
            f"Main drivers: {factor_str}",
            env_note,
            "",
            "---",
            "Report actual time after your first shot.",
        ]

    return "\n".join(line for line in lines if line is not None)


def format_warm_recommendation(suggested: float, last_setting: float, lang: str = "zh") -> str:
    adjustment = round(suggested - last_setting, 4)
    if lang == "zh":
        if adjustment > 0:
            desc = f"调整 +{adjustment} 格  →  刻度 {suggested}"
        elif adjustment < 0:
            desc = f"调整 {adjustment} 格  →  刻度 {suggested}"
        else:
            desc = f"保持 {suggested} 不变"
        return (
            "── 今日建议 · WARM 模式 ──\n"
            f"{desc}\n"
            "\n"
            "今天以流速为准，味觉信号暂时忽略。\n"
            "冲完告诉我实际时间。"
        )
    else:
        if adjustment > 0:
            desc = f"Adjust +{adjustment} step(s)  →  setting {suggested}"
        elif adjustment < 0:
            desc = f"Adjust {adjustment} step(s)  →  setting {suggested}"
        else:
            desc = f"Hold at {suggested}"
        return (
            "── Today's recommendation · WARM mode ──\n"
            f"{desc}\n"
            "\n"
            "Trust the numbers today, not the taste.\n"
            "Report flow time after first shot."
        )


def format_stage_warning(stage: dict, lang: str = "zh") -> str:
    if stage["stage"] == "resting":
        return f"⚠️  {_message(stage, lang)}"
    elif stage["stage"] == "declining":
        return f"↘  {_message(stage, lang)}"
    return ""


def format_bootstrap_warning(shot_count: int, confidence: int, lang: str = "zh") -> str:
    remaining = 10 - shot_count
    if lang == "zh":
        return (
            f"\n⚠️  现在数据还不到 10 杯（{shot_count}/10），建议是基于通用参数计算的，不是你的个人公式。\n"
            f"   再积累 {remaining} 杯（大约一周）后会准确很多。"
        )
    else:
        return (
            f"\n⚠️  Bootstrap phase ({shot_count}/10 shots recorded).\n"
            f"   Recommendation is based on generic parameters — not your personal formula yet.\n"
            f"   Accumulate {remaining} more shot(s) (about a week) for significantly better accuracy."
        )


def format_purge_notice(last_setting: float, new_setting: float, lang: str = "zh") -> str:
    delta = round(new_setting - last_setting, 4)
    if lang == "zh":
        return (
            f"── 需要排粉杯 ──\n"
            f"刻度变化：{last_setting} → {new_setting}（{delta:+g} 格）\n"
            f"磨盘里还留有上次的粉，需要先排一杯。\n"
            f"排粉杯的时间会记录但不纳入模型。"
        )
    else:
        return (
            f"── Purge shot required ──\n"
            f"Setting changed: {last_setting} → {new_setting} ({delta:+g} step(s))\n"
            f"Residual grounds from the old setting are still in the burrs.\n"
            f"Run one purge shot first — its flow data will be logged but excluded from the model."
        )


def format_anomaly_report(bean: str, anomaly_count: int, patterns: list[str], lang: str = "zh") -> str:
    if lang == "zh":
        lines = [
            f"── 检测到异常规律：{bean} ──",
            f"已记录 {anomaly_count} 次异常，发现以下规律：",
        ]
        for p in patterns:
            lines.append(f"  · {p}")
        lines.append("\n建议结合这些规律解读后续推荐。")
    else:
        lines = [
            f"── Anomaly pattern detected: {bean} ──",
            f"{anomaly_count} anomalies logged. Patterns identified:",
        ]
        for p in patterns:
            lines.append(f"  · {p}")
        lines.append("\nConsider these patterns when interpreting future recommendations.")
    return "\n".join(lines)
