"""
Quarterly report generator
- Style guide: personal taste profile + grinder behaviour summary
- Lookup table: temp × humidity → recommended setting (reference card)
- Personal formula: linear regression fit from actual shot data
"""

import json
import os
import math
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(__file__))

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")

# Lookup table buckets
TEMP_BUCKETS = [
    (None, 18,  "< 18°C"),
    (18,   22,  "18–22°C"),
    (22,   26,  "22–26°C"),
    (26,   30,  "26–30°C"),
    (30,  None, "> 30°C"),
]
HUMIDITY_BUCKETS = [
    (None, 60,  "< 60%"),
    (60,   70,  "60–70%"),
    (70,   80,  "70–80%"),
    (80,   90,  "80–90%"),
    (90,  None, "> 90%"),
]
SPARSE_THRESHOLD = 3   # cells with fewer data points get a warning marker


# ── Data loading ───────────────────────────────────────────

def load_all_sessions(grinder: str, bean: str) -> list[dict]:
    """Load all sessions for a grinder × bean combination."""
    sessions = []
    if not os.path.exists(SESSIONS_DIR):
        return sessions
    for fname in sorted(os.listdir(SESSIONS_DIR)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(SESSIONS_DIR, fname), encoding="utf-8") as f:
            sess = json.load(f)
        if sess.get("grinder") == grinder and sess.get("bean") == bean:
            sessions.append(sess)
    return sessions


def _good_shots(sessions: list[dict]) -> list[dict]:
    """Extract shots that reflect genuine grind performance
    (excludes purge, technique errors, intentional, WARM)."""
    good = []
    for sess in sessions:
        if sess.get("warm_state") == "warm":
            continue
        for shot in sess.get("shots", []):
            if (shot.get("type") == "purge"
                    or shot.get("technique_error")
                    or shot.get("intentional")):
                continue
            good.append({
                **shot,
                "temp": sess.get("temp", 20),
                "humidity": sess.get("humidity", 60),
                "days_since_roast": sess.get("days_since_roast", 14),
                "date": sess.get("date"),
            })
    return good


# ── Regression (pure Python, no numpy) ────────────────────

def _mat_mul(A, B):
    """Multiply two matrices represented as lists of lists."""
    rows_A, cols_A = len(A), len(A[0])
    cols_B = len(B[0])
    C = [[0.0] * cols_B for _ in range(rows_A)]
    for i in range(rows_A):
        for j in range(cols_B):
            for k in range(cols_A):
                C[i][j] += A[i][k] * B[k][j]
    return C


def _transpose(A):
    return [[A[j][i] for j in range(len(A))] for i in range(len(A[0]))]


def _mat_inv_4x4(M):
    """Invert a 4×4 matrix using Gauss-Jordan elimination."""
    n = 4
    aug = [M[i][:] + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        if abs(aug[col][col]) < 1e-12:
            return None  # singular
        scale = aug[col][col]
        aug[col] = [x / scale for x in aug[col]]
        for row in range(n):
            if row != col:
                factor = aug[row][col]
                aug[row] = [aug[row][k] - factor * aug[col][k] for k in range(2 * n)]
    return [row[n:] for row in aug]


def fit_personal_formula(shots: list[dict], bean_target_days: int = 14) -> dict | None:
    """
    Fit: setting = a + b×humidity + c×temp + d×(days_since_roast - target_days)

    Only uses shots where flow deviation ≤ 2s (actual good shots).
    Returns coefficient dict or None if insufficient data.
    """
    TARGET_FLOW_TOLERANCE = 2.0
    good = [
        s for s in shots
        if s.get("flow_time") is not None
        and s.get("setting") is not None
        and abs(s["flow_time"] - s.get("target_time_s", 28)) <= TARGET_FLOW_TOLERANCE
    ]

    if len(good) < 8:
        return None  # not enough data

    # Build X matrix: [1, humidity, temp, days_delta]
    X = []
    y = []
    for s in good:
        hum = s.get("humidity", 60)
        tmp = s.get("temp", 20)
        days_delta = s.get("days_since_roast", bean_target_days) - bean_target_days
        X.append([1.0, hum, tmp, float(days_delta)])
        y.append([s["setting"]])

    Xt = _transpose(X)
    XtX = _mat_mul(Xt, X)
    XtX_inv = _mat_inv_4x4(XtX)
    if XtX_inv is None:
        return None

    Xty = _mat_mul(Xt, y)
    coeffs = _mat_mul(XtX_inv, Xty)
    a, b, c, d = [coeffs[i][0] for i in range(4)]

    # R² calculation
    y_mean = sum(s["setting"] for s in good) / len(good)
    ss_tot = sum((s["setting"] - y_mean) ** 2 for s in good)
    ss_res = sum(
        (s["setting"] - (a + b * s["humidity"] + c * s["temp"]
                         + d * (s["days_since_roast"] - bean_target_days))) ** 2
        for s in good
    )
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    return {
        "intercept": round(a, 3),
        "humidity_coeff": round(b, 4),
        "temp_coeff": round(c, 4),
        "days_coeff": round(d, 4),
        "days_baseline": bean_target_days,
        "r2": round(r2, 3),
        "n_shots": len(good),
    }


# ── Lookup table ───────────────────────────────────────────

def _bucket_index(value, buckets):
    for i, (lo, hi, _) in enumerate(buckets):
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return i
    return len(buckets) - 1


def build_lookup_table(shots: list[dict]) -> dict:
    """
    Build a temp × humidity → recommended setting lookup table.
    Each cell stores list of settings from shots that produced good flow.
    """
    TARGET_FLOW_TOLERANCE = 2.5
    table = [[[] for _ in HUMIDITY_BUCKETS] for _ in TEMP_BUCKETS]

    for s in shots:
        if s.get("flow_time") is None or s.get("setting") is None:
            continue
        # Use shots that hit close to target
        target = s.get("target_time_s", 28)
        if abs(s["flow_time"] - target) > TARGET_FLOW_TOLERANCE:
            continue
        ti = _bucket_index(s["temp"], TEMP_BUCKETS)
        hi = _bucket_index(s["humidity"], HUMIDITY_BUCKETS)
        table[ti][hi].append(s["setting"])

    return table


def _cell_value(settings: list[float]) -> tuple[float | None, bool]:
    """Return (mean setting, is_sparse)."""
    if not settings:
        return None, True
    return round(sum(settings) / len(settings), 1), len(settings) < SPARSE_THRESHOLD


# ── Bean-specific analysis ─────────────────────────────────

def _bean_analysis(shots: list[dict], bean_profile: dict, lang: str = "zh") -> list[str]:
    """
    Analyse how this specific bean performed for this user:
    - flavor_baseline accuracy vs actual taste
    - actual peak window derived from data
    - late-stage decline signal
    - overall bean behaviour assessment
    """
    scored = [s for s in shots if s.get("taste") is not None and s.get("days_since_roast") is not None]
    flavor_baseline = bean_profile.get("flavor_baseline", 0.0)
    process  = bean_profile.get("process", "washed")
    roast    = bean_profile.get("roast_level", "medium")
    bean_name = bean_profile.get("name", "")

    zh = (lang == "zh")
    lines = [f"## {'这支豆子的表现分析' if zh else 'Bean Performance Analysis'}", ""]

    if not scored:
        lines.append("数据不足，无法分析。" if zh else "Not enough scored shots to analyse.")
        return lines

    actual_avg = sum(s["taste"] for s in scored) / len(scored)
    baseline_gap = round(actual_avg - flavor_baseline, 2)

    # ── flavor_baseline 准确性 ──
    if zh:
        lines.append(f"**风味预期 vs 实际表现**")
        lines.append(f"系统预设 {process}/{roast} 的风味基准为 **{flavor_baseline:+.2f}**，"
                     f"你的实际平均评分为 **{round(actual_avg, 2):+.2f}**，偏差 {baseline_gap:+.2f}。")
        if abs(baseline_gap) < 0.1:
            lines.append("> 预期与实测吻合——这支豆子的表现符合其处理法和烘焙度的典型特征。")
        elif baseline_gap < -0.1:
            lines.append(f"> 这支豆子在你手里比预期**更亮/更酸**——可能是烘焙偏浅、批次偏差，或你的萃取习惯偏短。"
                         f"建议下季度更新 flavor_baseline 为 {round(flavor_baseline + baseline_gap * 0.5, 2)}。")
        else:
            lines.append(f"> 这支豆子在你手里比预期**更苦/更重**——可能是烘焙偏深、豆子老化快，或萃取偏过。"
                         f"建议下季度更新 flavor_baseline 为 {round(flavor_baseline + baseline_gap * 0.5, 2)}。")
        lines.append("")
    else:
        lines.append(f"**Flavour baseline accuracy**")
        lines.append(f"System preset for {process}/{roast}: **{flavor_baseline:+.2f}**. "
                     f"Your actual average: **{round(actual_avg, 2):+.2f}**. Gap: {baseline_gap:+.2f}.")
        if abs(baseline_gap) < 0.1:
            lines.append("> Preset matches actual — this bean behaves as expected for its process and roast level.")
        elif baseline_gap < -0.1:
            lines.append(f"> This bean tastes **brighter/more sour** than expected. "
                         f"Consider updating flavor_baseline to {round(flavor_baseline + baseline_gap * 0.5, 2)} next quarter.")
        else:
            lines.append(f"> This bean tastes **more bitter/heavy** than expected. "
                         f"Consider updating flavor_baseline to {round(flavor_baseline + baseline_gap * 0.5, 2)} next quarter.")
        lines.append("")

    # ── 实测最佳赏味窗口 ──
    # 按 days_since_roast 分段，找平均 taste 最接近 0 的区间
    buckets = [(7, 14), (14, 21), (21, 28), (28, 35), (35, 50)]
    bucket_scores = {}
    for lo, hi in buckets:
        in_bucket = [s["taste"] for s in scored if lo <= s["days_since_roast"] < hi]
        if len(in_bucket) >= 2:
            avg_b = sum(in_bucket) / len(in_bucket)
            bucket_scores[(lo, hi)] = (round(avg_b, 2), len(in_bucket))

    if bucket_scores:
        best_bucket = min(bucket_scores, key=lambda k: abs(bucket_scores[k][0]))
        best_avg, best_n = bucket_scores[best_bucket]
        if zh:
            lines.append("**实测最佳赏味窗口**")
            lines.append(f"根据你的数据，烘焙后第 **{best_bucket[0]}–{best_bucket[1]} 天**口感最接近平衡"
                         f"（平均评分 {best_avg:+.2f}，{best_n} 杯）。")
            all_buckets_str = "  ".join(
                f"第{lo}–{hi}天：{v[0]:+.2f}（{v[1]}杯）"
                for (lo, hi), v in sorted(bucket_scores.items())
            )
            lines += [f"各阶段均值：{all_buckets_str}", ""]
        else:
            lines.append("**Actual peak window**")
            lines.append(f"Based on your data, days **{best_bucket[0]}–{best_bucket[1]}** post-roast "
                         f"produced the most balanced shots (avg {best_avg:+.2f}, {best_n} shots).")
            all_buckets_str = "  ".join(
                f"d{lo}–{hi}: {v[0]:+.2f} ({v[1]})"
                for (lo, hi), v in sorted(bucket_scores.items())
            )
            lines += [f"All stages: {all_buckets_str}", ""]

    # ── 衰退期信号 ──
    # 比较前半段 vs 后半段的流速和口感趋势
    days_vals = sorted(set(s["days_since_roast"] for s in scored))
    if len(days_vals) >= 4:
        mid = days_vals[len(days_vals) // 2]
        early = [s for s in scored if s["days_since_roast"] < mid]
        late  = [s for s in scored if s["days_since_roast"] >= mid]

        if early and late:
            early_taste = sum(s["taste"] for s in early) / len(early)
            late_taste  = sum(s["taste"] for s in late)  / len(late)
            taste_drift = round(late_taste - early_taste, 2)

            early_flow = [s["flow_time"] for s in early if s.get("flow_time") is not None]
            late_flow  = [s["flow_time"] for s in late  if s.get("flow_time") is not None]
            flow_drift = round(
                sum(late_flow)/len(late_flow) - sum(early_flow)/len(early_flow), 1
            ) if early_flow and late_flow else None

            if zh:
                lines.append("**衰退期信号**")
                lines.append(f"前半段（≤第{mid}天）vs 后半段（>第{mid}天）：")
                lines.append(f"- 口感偏移：{taste_drift:+.2f}（正值=越来越苦，负值=越来越酸）")
                if flow_drift is not None:
                    lines.append(f"- 流速偏移：{flow_drift:+.1f}s（正值=越来越慢）")
                if taste_drift > 0.2 or (flow_drift and flow_drift > 1.5):
                    lines.append(f"> ⚠️  后期出现明显苦感加重或流速下降——这支豆子在你手里大约第 {mid} 天后性价比开始下降。")
                elif taste_drift < -0.2:
                    lines.append(f"> 后期酸感增加——可能是豆子老化后萃取更难，或你的设定没有及时跟上衰退补偿。")
                else:
                    lines.append("> 前后期表现稳定，豆子老化影响在你的刻度调整范围内可控。")
                lines.append("")
            else:
                lines.append("**Decline signal**")
                lines.append(f"Early (≤day {mid}) vs late (>day {mid}):")
                lines.append(f"- Taste drift: {taste_drift:+.2f} (positive = getting more bitter)")
                if flow_drift is not None:
                    lines.append(f"- Flow drift: {flow_drift:+.1f}s (positive = getting slower)")
                if taste_drift > 0.2 or (flow_drift and flow_drift > 1.5):
                    lines.append(f"> ⚠️  Noticeable bitterness increase or flow slowdown after day {mid} — diminishing returns after that point.")
                elif taste_drift < -0.2:
                    lines.append(f"> Sourness increasing in later days — ageing may be making extraction harder, or grind compensation is lagging.")
                else:
                    lines.append("> Stable throughout — bean ageing is well-managed within your adjustment range.")
                lines.append("")

    return lines


# ── Style guide ────────────────────────────────────────────

def _taste_profile(shots: list[dict]) -> dict:
    scored = [s for s in shots if s.get("taste") is not None]
    if not scored:
        return {"direction": "unknown", "avg": None, "n": 0}
    avg = sum(s["taste"] for s in scored) / len(scored)
    if avg < -0.15:
        direction = "sour-leaning"
    elif avg > 0.15:
        direction = "bitter-leaning"
    else:
        direction = "balanced"
    return {"direction": direction, "avg": round(avg, 2), "n": len(scored)}


def _flow_stats(shots: list[dict]) -> dict:
    flows = [s["flow_time"] for s in shots if s.get("flow_time") is not None]
    if not flows:
        return {"mean": None, "std": None, "n": 0}
    mean = sum(flows) / len(flows)
    std = (sum((f - mean) ** 2 for f in flows) / len(flows)) ** 0.5
    return {"mean": round(mean, 1), "std": round(std, 1), "n": len(flows)}


def _days_distribution(shots: list[dict]) -> dict:
    days_list = [s["days_since_roast"] for s in shots if s.get("days_since_roast") is not None]
    if not days_list:
        return {"mean": None, "min": None, "max": None}
    return {
        "mean": round(sum(days_list) / len(days_list)),
        "min":  min(days_list),
        "max":  max(days_list),
    }


def _build_personal_profile(
    shots: list[dict],
    sessions: list[dict],
    taste: dict,
    env: dict,
    warm: dict,
    formula: dict | None,
    lang: str = "zh",
) -> list[str]:
    """
    Generate a narrative personal style summary in the user's language.
    Covers: extraction preference, peak-day habit, environmental sensitivity,
    grinder+bean behaviour, and coefficient comparison if formula exists.
    """
    flow  = _flow_stats(shots)
    days  = _days_distribution(shots)
    settings = [s["setting"] for s in shots if s.get("setting") is not None]
    s_min = min(settings) if settings else None
    s_max = max(settings) if settings else None
    s_mean = round(sum(settings) / len(settings), 2) if settings else None

    if lang == "zh":
        lines = ["## 个人风格总结", ""]

        # ── 萃取偏好 ──
        avg = taste["avg"]
        n_taste = taste["n"]
        if taste["direction"] == "sour-leaning":
            pref = f"偏酸/偏亮（平均味觉分 {avg}，共 {n_taste} 次有效评分）"
            pref_note = "你倾向于在萃取不足边缘拉杆——风味层次感强，但容忍度窄。建议流速目标可略微调短。"
        elif taste["direction"] == "bitter-leaning":
            pref = f"偏苦/偏浓（平均味觉分 {avg}，共 {n_taste} 次有效评分）"
            pref_note = "你倾向于过萃方向——口感厚重，但长期偏高容易掩盖豆子原本的酸质。"
        else:
            pref = f"平衡（平均味觉分 {avg}，共 {n_taste} 次有效评分）"
            pref_note = "你的萃取稳定在目标区间，说明刻度判断和手法都比较一致。"
        lines += [f"**萃取偏好：** {pref}", f"> {pref_note}", ""]

        # ── 赏味阶段偏好 ──
        if days["mean"] is not None:
            lines += [
                f"**赏味阶段偏好：** 你通常在烘焙后第 {days['min']}–{days['max']} 天使用这款豆子，"
                f"集中在第 {days['mean']} 天前后。",
            ]
            if days["mean"] < 14:
                lines.append("> 你倾向于在开窗期就开始使用——风味变化快，每天调整幅度可能较大，属于正常现象。")
            elif days["mean"] > 28:
                lines.append("> 你倾向于使用较老的豆子——此阶段需要持续调细补偿，days_coeff 会在公式里体现。")
            else:
                lines.append("> 集中在最佳赏味窗口，豆子参数相对稳定。")
            lines.append("")

        # ── 流速稳定性 ──
        if flow["std"] is not None:
            lines.append(f"**流速稳定性：** 平均 {flow['mean']}s，标准差 {flow['std']}s")
            if flow["std"] <= 1.0:
                lines.append("> 流速非常稳定——说明布粉手法和压粉力度一致性高，模型数据质量好。")
            elif flow["std"] <= 2.0:
                lines.append("> 流速稳定性一般——有一定手法波动，属正常范围，不影响模型可用性。")
            else:
                lines.append("> 流速波动较大——可能存在布粉/压粉不一致，建议排查手法，否则会降低公式精度。")
            lines.append("")

        # ── 磨豆机+豆子行为 ──
        if s_min is not None:
            lines += [
                f"**{' × '.join(['磨豆机', '豆子'])}行为：** 本季度刻度范围 {s_min}–{s_max}，"
                f"均值 {s_mean}",
                f"WARM 率 {warm['warm_pct']}%（{warm['warm_sessions']}/{warm['total_sessions']} 次 session）",
            ]
            if warm["warm_pct"] > 30:
                lines.append("> ⚠️  WARM 率偏高——超过 30% 的数据靠流速驱动而非味觉，公式精度受影响。")
            lines.append("")

        # ── 系数对比 ──
        if formula:
            generic_tc = 0.05
            generic_hc = 0.01
            tc_diff = round(formula["temp_coeff"] - generic_tc, 4)
            hc_diff = round(formula["humidity_coeff"] - (-generic_hc if formula["humidity_coeff"] < 0 else generic_hc), 4)
            lines += [
                "**系数对比（个人实测 vs 行业估算）：**",
                "",
                f"| 因素 | 行业估算 | 你的实测值 | 差异 |",
                f"|------|----------|------------|------|",
                f"| 温度（每1°C） | 0.05 格 | {formula['temp_coeff']} 格 | {tc_diff:+.4f} |",
                f"| 湿度（每1%） | ±0.01 格 | {formula['humidity_coeff']} 格 | {formula['humidity_coeff'] - 0.01:+.4f} |",
                "",
            ]
            if abs(formula["temp_coeff"]) < abs(generic_tc) * 0.6:
                lines.append("> 你的磨豆机对温度变化不如行业平均敏感——说明你的环境温度波动对萃取影响较小，或磨盘散热好。")
            elif abs(formula["temp_coeff"]) > abs(generic_tc) * 1.4:
                lines.append("> 你的磨豆机对温度变化比行业平均更敏感——温差超过 2°C 时需要更大的刻度补偿。")
            if formula["humidity_coeff"] < 0:
                lines.append("> 湿度系数为负——湿度升高时你需要调细，符合湿豆结块、流速减慢的规律。")
            lines.append("")

    else:  # English
        lines = ["## Personal Style Profile", ""]

        avg = taste["avg"]
        n_taste = taste["n"]
        if taste["direction"] == "sour-leaning":
            pref = f"Sour-leaning (avg taste score {avg}, {n_taste} rated shots)"
            pref_note = "You tend to pull on the under-extracted side — complex and bright, but narrow tolerance. Consider shortening your target time slightly."
        elif taste["direction"] == "bitter-leaning":
            pref = f"Bitter-leaning (avg taste score {avg}, {n_taste} rated shots)"
            pref_note = "You pull towards over-extraction — full-bodied, but consistent bitterness can mask the bean's origin character."
        else:
            pref = f"Balanced (avg taste score {avg}, {n_taste} rated shots)"
            pref_note = "Your extractions consistently land on target — grind judgement and technique are well-calibrated."
        lines += [f"**Extraction preference:** {pref}", f"> {pref_note}", ""]

        if days["mean"] is not None:
            lines += [
                f"**Peak-day habit:** You typically use this bean between day {days['min']}–{days['max']} post-roast, "
                f"centred around day {days['mean']}.",
            ]
            if days["mean"] < 14:
                lines.append("> You tend to start early in the opening window — fast-changing flavour means larger daily adjustments are normal.")
            elif days["mean"] > 28:
                lines.append("> You tend to use older beans — the days_coeff in your formula will reflect the consistent finer compensation needed.")
            else:
                lines.append("> Centred in the peak window — bean parameters are relatively stable.")
            lines.append("")

        if flow["std"] is not None:
            lines.append(f"**Flow consistency:** Mean {flow['mean']}s, std dev {flow['std']}s")
            if flow["std"] <= 1.0:
                lines.append("> Very consistent — distribution and tamping are highly repeatable. Model data quality is high.")
            elif flow["std"] <= 2.0:
                lines.append("> Moderate consistency — some technique variation, within normal range.")
            else:
                lines.append("> High flow variance — inconsistent distribution/tamping likely. This reduces formula accuracy.")
            lines.append("")

        if s_min is not None:
            lines += [
                f"**Grinder × Bean behaviour:** Setting range this quarter: {s_min}–{s_max} (mean {s_mean})",
                f"WARM rate: {warm['warm_pct']}%  ({warm['warm_sessions']}/{warm['total_sessions']} sessions)",
            ]
            if warm["warm_pct"] > 30:
                lines.append("> ⚠️  High WARM rate — over 30% of data is flow-driven only. Formula accuracy may be reduced.")
            lines.append("")

        if formula:
            generic_tc = 0.05
            tc_diff = round(formula["temp_coeff"] - generic_tc, 4)
            lines += [
                "**Coefficient comparison (personal vs generic estimate):**",
                "",
                f"| Factor | Generic | Your value | Diff |",
                f"|--------|---------|------------|------|",
                f"| Temperature (per 1°C) | 0.05 steps | {formula['temp_coeff']} steps | {tc_diff:+.4f} |",
                f"| Humidity (per 1%) | ±0.01 steps | {formula['humidity_coeff']} steps | {formula['humidity_coeff'] - 0.01:+.4f} |",
                "",
            ]
            if abs(formula["temp_coeff"]) < abs(generic_tc) * 0.6:
                lines.append("> Your grinder is less temperature-sensitive than average — small temp changes have less impact on extraction.")
            elif abs(formula["temp_coeff"]) > abs(generic_tc) * 1.4:
                lines.append("> Your grinder is more temperature-sensitive than average — temp swings over 2°C need larger grind compensation.")
            if formula["humidity_coeff"] < 0:
                lines.append("> Negative humidity coefficient — higher humidity makes you grind finer, consistent with clumping behaviour.")
            lines.append("")

    return lines


def _env_sensitivity(shots: list[dict]) -> dict:
    """Estimate which environmental factor drives more adjustment."""
    hum_variance = 0.0
    tmp_variance = 0.0
    if len(shots) > 3:
        humidities = [s["humidity"] for s in shots if s.get("humidity") is not None]
        temps = [s["temp"] for s in shots if s.get("temp") is not None]
        if humidities:
            mean_h = sum(humidities) / len(humidities)
            hum_variance = sum((h - mean_h) ** 2 for h in humidities) / len(humidities)
        if temps:
            mean_t = sum(temps) / len(temps)
            tmp_variance = sum((t - mean_t) ** 2 for t in temps) / len(temps)

    if hum_variance > tmp_variance * 2:
        dominant = "humidity (high variation in your environment)"
    elif tmp_variance > hum_variance * 2:
        dominant = "temperature"
    else:
        dominant = "both roughly equal"
    return {
        "dominant": dominant,
        "humidity_variance": round(hum_variance, 1),
        "temp_variance": round(tmp_variance, 1),
    }


def _warm_stats(sessions: list[dict]) -> dict:
    total = len(sessions)
    warm = sum(1 for s in sessions if s.get("warm_state") == "warm")
    pct = round(warm / total * 100) if total else 0
    return {"total_sessions": total, "warm_sessions": warm, "warm_pct": pct}


# ── Lookup table used as session starting point ────────────

def get_table_suggestion(grinder: str, bean: str, temp: float, humidity: float) -> float | None:
    """
    Look up the seasonal table for a recommended starting setting
    given today's environment. Returns None if no table exists or cell is empty.
    """
    report = _latest_report(grinder, bean)
    if report is None:
        return None
    table = report.get("lookup_table")
    if table is None:
        return None
    ti = _bucket_index(temp, TEMP_BUCKETS)
    hi = _bucket_index(humidity, HUMIDITY_BUCKETS)
    cell = table[ti][hi]
    if not cell:
        return None
    return round(sum(cell) / len(cell), 1)


def _latest_report(grinder: str, bean: str) -> dict | None:
    if not os.path.exists(REPORTS_DIR):
        return None
    candidates = [
        f for f in os.listdir(REPORTS_DIR)
        if f.endswith(".json") and grinder in f and bean.replace(" ", "_") in f
    ]
    if not candidates:
        return None
    latest = sorted(candidates)[-1]
    with open(os.path.join(REPORTS_DIR, latest), encoding="utf-8") as f:
        return json.load(f)


# ── Quarterly check ────────────────────────────────────────

def current_quarter() -> str:
    d = date.today()
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def check_quarterly_report(grinder: str, bean: str, shot_count: int) -> bool:
    """
    Returns True if a quarterly report should be generated.
    Conditions: ≥20 shots AND no report for the current quarter yet.
    """
    if shot_count < 20:
        return False
    quarter = current_quarter()
    if not os.path.exists(REPORTS_DIR):
        return True
    for f in os.listdir(REPORTS_DIR):
        if quarter in f and grinder in f and bean.replace(" ", "_") in f:
            return False
    return True


# ── Report generation ──────────────────────────────────────

def generate_report(grinder: str, bean: str, bean_target_days: int = 14, lang: str = "zh") -> str:
    """
    Generate the full quarterly report and save to:
      data/reports/{quarter}-{grinder}-{bean}.md
      data/reports/{quarter}-{grinder}-{bean}.json  (lookup table data)

    Returns the markdown report as a string.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)
    quarter = current_quarter()
    today = date.today().isoformat()

    sessions = load_all_sessions(grinder, bean)
    shots = _good_shots(sessions)

    if len(shots) < 8:
        return f"Not enough data yet ({len(shots)} usable shots). Need at least 8 to generate a report."

    taste      = _taste_profile(shots)
    env        = _env_sensitivity(shots)
    warm       = _warm_stats(sessions)
    formula    = fit_personal_formula(shots, bean_target_days)
    table_data = build_lookup_table(shots)

    from setup import load_bean
    try:
        bean_profile = load_bean(bean)
    except FileNotFoundError:
        bean_profile = {}

    zh = (lang == "zh")

    # ── Header ──────────────────────────────────────────────
    title      = f"# {'研磨档案' if zh else 'Dialing Profile'} — {grinder} × {bean}"
    meta       = (f"季度：{quarter}  ·  生成日期：{today}  ·  基于 {len(shots)} 杯数据（{len(sessions)} 次 session）"
                  if zh else
                  f"Quarter: {quarter}  ·  Generated: {today}  ·  Based on {len(shots)} shots ({len(sessions)} sessions)")
    lines = [title, meta, "", "---", ""]

    # ── Personal Style Profile ──────────────────────────────
    lines += _build_personal_profile(shots, sessions, taste, env, warm, formula, lang=lang)
    lines += ["---", ""]

    # ── Bean-specific analysis ──────────────────────────────
    lines += _bean_analysis(shots, bean_profile, lang=lang)
    lines += ["---", ""]

    # ── Seasonal lookup table ────────────────────────────────
    if zh:
        lines += [
            "## 季节性刻度参考表",
            "",
            f"磨豆机：{grinder}  ·  季度：{quarter}",
            "以此表作为当日起始刻度。标 * 的格子数据点不足 3 个，仅供参考。",
            "",
        ]
    else:
        lines += [
            "## Seasonal lookup table",
            "",
            f"Grinder: {grinder}  ·  Season: {quarter}",
            "Use this table as your starting point. Cells marked * have fewer than 3 data points — treat as approximate.",
            "",
        ]

    hum_headers = " | ".join(f"{b[2]:^12}" for b in HUMIDITY_BUCKETS)
    temp_col    = "温度 \\ 湿度" if zh else "Temp \\ Humidity"
    lines.append(f"| {temp_col} | {hum_headers} |")
    lines.append("|" + "---|" * (len(HUMIDITY_BUCKETS) + 1))

    for ti, (_, _, t_label) in enumerate(TEMP_BUCKETS):
        row = [f"**{t_label}**"]
        for hi in range(len(HUMIDITY_BUCKETS)):
            val, sparse = _cell_value(table_data[ti][hi])
            row.append("  —  " if val is None else f"{val}{'*' if sparse else ' ':^6}")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ── Personal formula ────────────────────────────────────
    lines += ["---", "", f"## {'个人公式' if zh else 'Personal formula'}"]
    if formula:
        a, b, c, d = formula["intercept"], formula["humidity_coeff"], formula["temp_coeff"], formula["days_coeff"]
        bl, r2, n  = formula["days_baseline"], formula["r2"], formula["n_shots"]
        b_sign = "+" if b >= 0 else "-"
        c_sign = "+" if c >= 0 else "-"
        d_sign = "+" if d >= 0 else "-"

        if zh:
            fit_label = ("强拟合" if r2 >= 0.8 else "中等拟合" if r2 >= 0.6 else "弱拟合" if r2 >= 0.4 else "较差")
            lines += [
                f"基于 {n} 杯数据拟合  ·  R² = {r2}  [{fit_label}]（1.0 = 完美拟合）",
                "",
                "```",
                f"刻度 = {a}",
                f"     {b_sign} {abs(b):.4f} × (湿度 - 60)",
                f"     {c_sign} {abs(c):.4f} × (温度 - 20)",
                f"     {d_sign} {abs(d):.4f} × (烘焙天数 - {bl})",
                "```",
                "",
            ]
            if r2 < 0.5:
                lines.append("> ⚠️  R² 偏低，拟合较弱。继续积累不同环境条件下的数据可以提升精度。")
            elif r2 >= 0.8:
                lines.append("> ✓  强拟合——公式可靠反映你的研磨规律。")
            lines += [
                "",
                "### 没有 app 时手动使用方法",
                "",
                "1. 查当天温度和湿度。",
                "2. 记录豆子烘焙后天数。",
                "3. 代入上面的公式。",
                "4. 从该刻度出发，第一杯偏差超过 ±3s 再微调。",
                "",
            ]
        else:
            fit_label = ("strong" if r2 >= 0.8 else "moderate" if r2 >= 0.6 else "weak" if r2 >= 0.4 else "poor")
            lines += [
                f"Fitted from {n} shots  ·  R² = {r2}  [{fit_label} fit]  (1.0 = perfect)",
                "",
                "```",
                f"setting = {a}",
                f"        {b_sign} {abs(b):.4f} × (humidity - 60)",
                f"        {c_sign} {abs(c):.4f} × (temp - 20)",
                f"        {d_sign} {abs(d):.4f} × (days_since_roast - {bl})",
                "```",
                "",
            ]
            if r2 < 0.5:
                lines.append("> ⚠️  R² is low — more data from varied conditions will improve accuracy.")
            elif r2 >= 0.8:
                lines.append("> ✓  Strong fit — this formula reliably captures your dialing pattern.")
            lines += [
                "",
                "### How to use without the app",
                "",
                "1. Check today's temperature and humidity.",
                "2. Note the bean's days since roast.",
                "3. Plug into the formula above.",
                "4. Start there. Adjust if first shot is off by more than ±3s.",
                "",
            ]
    else:
        if zh:
            lines += [f"数据不足，无法拟合公式（需要 ≥8 杯流速偏差在 ±2.5s 内的数据，当前 {len(shots)} 杯）。", ""]
        else:
            lines += [f"Not enough consistent shots yet. Need ≥8 shots within ±2.5s of target. Currently {len(shots)}.", ""]

    # ── Data range appendix ─────────────────────────────────
    if shots:
        temps    = [s["temp"] for s in shots if s.get("temp") is not None]
        hums     = [s["humidity"] for s in shots if s.get("humidity") is not None]
        days_l   = [s["days_since_roast"] for s in shots if s.get("days_since_roast") is not None]
        settings = [s["setting"] for s in shots if s.get("setting") is not None]

        if zh:
            lines += [
                "---", "",
                "## 本季度数据范围", "",
                "| 变量 | 最小值 | 最大值 | 均值 |",
                "|------|--------|--------|------|",
                f"| 温度 | {min(temps):.0f}°C | {max(temps):.0f}°C | {sum(temps)/len(temps):.1f}°C |",
                f"| 湿度 | {min(hums):.0f}% | {max(hums):.0f}% | {sum(hums)/len(hums):.1f}% |",
                f"| 烘焙后天数 | {min(days_l)} | {max(days_l)} | {sum(days_l)/len(days_l):.0f} |",
                f"| 使用刻度 | {min(settings):.1f} | {max(settings):.1f} | {sum(settings)/len(settings):.1f} |",
                "",
            ]
        else:
            lines += [
                "---", "",
                "## Data range (this quarter)", "",
                "| Variable | Min | Max | Mean |",
                "|----------|-----|-----|------|",
                f"| Temperature | {min(temps):.0f}°C | {max(temps):.0f}°C | {sum(temps)/len(temps):.1f}°C |",
                f"| Humidity | {min(hums):.0f}% | {max(hums):.0f}% | {sum(hums)/len(hums):.1f}% |",
                f"| Days since roast | {min(days_l)} | {max(days_l)} | {sum(days_l)/len(days_l):.0f} |",
                f"| Settings used | {min(settings):.1f} | {max(settings):.1f} | {sum(settings)/len(settings):.1f} |",
                "",
            ]

    report_md = "\n".join(lines)

    # Save markdown report
    safe_bean = bean.replace(" ", "_")
    md_path = os.path.join(REPORTS_DIR, f"{quarter}-{grinder}-{safe_bean}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    # Save JSON (for programmatic lookup table access)
    json_path = os.path.join(REPORTS_DIR, f"{quarter}-{grinder}-{safe_bean}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "quarter": quarter,
            "grinder": grinder,
            "bean": bean,
            "generated": today,
            "total_shots": len(shots),
            "total_sessions": len(sessions),
            "taste_profile": taste,
            "formula": formula,
            "lookup_table": table_data,
        }, f, ensure_ascii=False, indent=2)

    print(f"✓ Report saved: {md_path}")

    # ── 把个人公式系数写回 bean 档案 ──────────────────────────
    # 无论 R² 高低都激活——质量信息透传给用户，让用户自己判断
    if formula:
        from setup import load_bean, save_bean
        bean_profile = load_bean(bean)
        bean_profile["personal_formula"] = {
            "temp_coeff":     formula["temp_coeff"],
            "humidity_coeff": formula["humidity_coeff"],
            "days_coeff":     formula["days_coeff"],
            "r2":             formula["r2"],
            "n_shots":        formula["n_shots"],
            "fitted_at":      today,
        }
        save_bean(bean_profile)

        r2 = formula["r2"]
        if r2 >= 0.8:
            quality = "强拟合 — 系数可信度高"
            advice  = "推荐精度应明显提升。"
        elif r2 >= 0.6:
            quality = "中等拟合 — 系数基本可靠"
            advice  = "推荐精度会有改善，继续积累数据可进一步提升。"
        elif r2 >= 0.4:
            quality = "弱拟合 — 系数仅供参考"
            advice  = "环境噪音较大，建议在更多不同温湿度条件下积累数据后重新拟合。"
        else:
            quality = "拟合较差 — 数据噪音大"
            advice  = "系数已激活但可信度低。可能原因：数据量少、环境条件变化范围窄、布粉手法不稳定。"

        print(
            f"\n✦ 个人公式已激活（基于 {formula['n_shots']} 杯数据）\n"
            f"  R² = {r2}  [{quality}]\n"
            f"  温度系数：{formula['temp_coeff']}（经验估算值 0.05）\n"
            f"  湿度系数：{formula['humidity_coeff']}（经验估算值 0.01）\n"
            f"  {advice}\n"
            f"  从下次 session 开始生效。"
        )

    return report_md


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate quarterly dialing report")
    parser.add_argument("--grinder", required=True)
    parser.add_argument("--bean",    required=True)
    parser.add_argument("--target-days", type=int, default=14,
                        help="Bean's peak days post-roast (used as regression baseline)")
    parser.add_argument("--lang", choices=["zh", "en"], default="zh")
    args = parser.parse_args()

    report = generate_report(args.grinder, args.bean, args.target_days, lang=args.lang)
    print()
    print(report)
