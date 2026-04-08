# Coffee Dialing Agent — Implementation Checklist

> Purpose: cross-reference against spec.md before writing code
> Format: [ ] not implemented / [x] complete / [~] partial

---

## Project structure

```
coffee-agent/
├── CLAUDE.md               # agent instructions
├── spec.md                 # design specification
├── checklist.md            # this file
├── data/
│   ├── grinders/           # grinder profiles {name}.json
│   ├── beans/              # bean profiles {name}.json
│   ├── sessions/           # daily session records YYYY-MM-DD.json
│   ├── vocab/              # personal taste vocab personal.json
│   └── anomalies/          # anomaly log {bean_id}.json
└── scripts/
    ├── setup.py            # init: create grinder and bean profiles
    ├── calibrate.py        # β coefficient calibration
    ├── calc_freshness.py   # freshness decay + flavour window
    ├── calc_grind.py       # grind offset calculation
    ├── calc_ey.py          # extraction yield (optional)
    ├── calc_confidence.py  # confidence score
    ├── session.py          # daily session flow
    ├── vocab.py            # taste vocabulary mapping
    ├── weather.py          # temp/humidity source (optional)
    └── output.py           # formatted output
```

---

## 1. Initialisation — `setup.py`

### 1.1 Capacity validation
- [x] `validate_capacity()` — grinders ≤ 2, beans ≤ 3, error and reject on overflow
- [x] Each grinder × bean combination maintains independent data (no cross-contamination)

### 1.2 Grinder profile
- [x] `create_grinder_profile(name, burr_type)`
- [x] Written to `data/grinders/{name}.json`: name, burr type, β (null until calibrated), total kg ground
- [x] Alert every 1,000 kg cumulative use → re-calibration prompt

### 1.3 β coefficient calibration — `calibrate.py`
- [x] `run_calibration(grinder_name)` — interactive flow, guides user through 3 shots
- [x] Each shot: adjust 0.5 steps finer, record flow time
- [x] `fit_beta(settings, flow_times)` — least-squares fit of setting-to-flow slope, returns β
- [x] β written to grinder profile

### 1.4 Bean profile
- [x] `create_bean_profile(name, origin, process, roast_level, roast_date, dose_g, yield_g, target_time_s)`
- [x] Written to `data/beans/{name}.json`
- [x] Process → density coefficient D: washed=1.0 / natural=0.9 / honey=0.95 / anaerobic=1.1
- [x] Roast level → hardness coefficient H: light=1.2 / medium-light=1.1 / medium=1.0 / medium-dark=0.85 / dark=0.7

---

## 2. Freshness decay — `calc_freshness.py`

- [x] `days_since_roast(roast_date)` → integer days from today
- [x] `freshness_offset(days)` — two-slope model:
  - Days ≤ 7 (resting): steep slope, rapid CO2 release, parameters unstable
  - Days > 7 (ageing): gentle linear decline
- [x] `flavor_stage(days, process_method)` → current stage + days remaining

| Process | Window | Peak | Decline |
|---------|--------|------|---------|
| Washed | +7 days | +14–+28 days | after +28 |
| Natural | +14 days | +21–+42 days | after +42 |
| Honey / Anaerobic | +10 days | +18–+35 days | after +35 |

- [x] Stage label output:
  - Resting → `"Wait X more days — parameters unstable"`
  - Peak → `"Currently in best flavour window"`
  - Declining → `"X days past peak — consider going finer"`

---

## 3. Grind offset — `calc_grind.py`

- [x] `calc_grind_offset(beta, freshness_offset, temp, temp_baseline, humidity, flow_deviation)`

```python
grind_offset = beta × (
    freshness_offset
    + temp_coefficient × (temp - temp_baseline)
    + humidity_coefficient × max(0, humidity - 60)
    + flow_correction(flow_deviation)
)
```

- [x] `temp_coefficient` initial value: 10°C swing → 5–10 µm particle shift, converted to steps
- [x] `humidity_coefficient` initial value: each 1% above 60% → +0.01 steps (finer direction)
- [x] `flow_correction(deviation_seconds)` — flow deviation → step adjustment
- [x] `suggested_setting(last_setting, grind_offset)` → today's recommended setting
- [x] `brew_ratio(yield_g, dose_g)` → ratio

---

## 4. Extraction yield — `calc_ey.py` (optional)

- [x] `calc_ey(tds_pct, yield_g, dose_g)` → EY% = (TDS% × yield_g) / dose_g × 100
- [x] Only called when user has a refractometer. Skipped when TDS unavailable. Does not affect main flow.

---

## 5. Confidence — `calc_confidence.py`

- [x] `calc_confidence(recent_n, warm_flags, missing_env_data)` → percentage

| Factor | Effect |
|--------|--------|
| Recent N shots (higher N = higher score) | Positive |
| WARM flag ratio | Negative (sensory data unreliable) |
| Missing env data (estimated values) | Negative |
| Data gaps (>3 days unlogged) | Negative |

- [x] `detect_warm_patterns(warm_history, window=30)` → if WARM frequency > 30% in last 30 days, auto-reduce sensory weight, alert user

---

## 6. Environment — `weather.py` (optional)

- [x] `fetch_weather_api(api_key, location)` → temp, humidity
- [x] `load_sensor_data(device_config)` → sensor integration (reserved interface)
- [x] Three-source logic: API → sensor → manual input
- [x] `setup_weather_source()` — first-run interactive config wizard (not silent fall-through to manual)
- [x] Config persisted to `data/weather_config.json` — source chosen once, reused every session
- [x] No config: show selection menu — never silently jump to manual input
- [x] Unconfigured: use yesterday's values, label "estimated", reduce confidence

---

## 7. Taste vocabulary — `vocab.py`

- [x] `load_vocab(user_id)` → reads `data/vocab/personal.json`
- [x] `map_taste_word(word, vocab)` → returns −1 / 0 / +1 / WARM_flag / None (unknown)
- [x] Unknown word → return None → trigger agent question: "When you say 'X' — sour or bitter?"
- [x] `update_vocab(word, value, user_id)` → write to vocab after user confirms
- [x] Vocab is user-specific — no shared default dictionary

---

## 8. WARM system — `session.py`

- [x] `check_warm()` → ask at session start, return `"normal"` / `"warm"`
- [x] `apply_warm_weight(sensory_value, warm_state)` → normal: weight=1.0, warm: weight=0.2
- [x] Under WARM: disable sensory-driven grind adjustment (flow correction only)
- [x] WARM state stored in `data/sessions/`, separate from main training
- [x] WARM output: `"Trust the numbers today, not the taste."`

---

## 9. Purge shot — `session.py` (addresses residual grounds problem)

- [x] `_is_setting_changed(last_setting, new_setting)` → True if change ≥ 0.5 steps
- [x] When setting changed: prompt purge shot before first real shot
- [x] Purge shot stored with `"type": "purge"`, excluded from model training
- [x] `_get_last_flow()` — rejects previous session's flow data when setting has changed (stale data from different grind size)
- [x] `count_total_shots()` — excludes purge shots from shot count

---

## 10. Intentional deviation flag — `session.py` (addresses flavour-first decisions)

- [x] After first real shot, if taste ≠ balanced: ask "Intentional choice? [y/N]"
- [x] Intentional shots stored with `"intentional": true`
- [x] Intentional shots excluded from model training
- [x] Intentional shots not logged to anomaly database

---

## 11. Technique error flag — `session.py` (addresses technique noise)

- [x] When flow deviation > 3s: ask "[g] grind issue / [t] technique error"
- [x] Technique errors stored with `"technique_error": true`
- [x] Technique errors excluded from grind model
- [x] Technique errors not logged to anomaly database
- [x] Same logic in `_record_additional_shots()`

---

## 12. Cold/warm start — `session.py`

### 12.1 Start protocol
- [x] On new bean: ask "Have you used this bean before?"
- [x] **Warm start**: `warm_start_input()` → collect current setting + recent feel → recommend immediately (low confidence)
- [x] **Cold start**: 3-day observation protocol

### 12.2 Cold start communication style detection
- [x] Day 1 open question: "Tell me about today's grind."
- [x] `detect_communication_style(response)` → `"verbose"` / `"qa"` / `"freeform"`

| Signal | Type | Strategy |
|--------|------|----------|
| ≥3 variables, concise | Self-structured | User leads, fill gaps only |
| Short, accurate | Q&A | Agent asks one at a time |
| Long but variable-sparse | Narrative | Let user finish, echo back |

### 12.3 Cold start close
- [x] Day 1 end: `echo_variables(extracted)` — list logged variables, ask for additions
- [x] Day 3 end (single transition question): "Before or after first shot?"
- [x] Preference stored, affects session timing

---

## 13. Daily session flow — `session.py`

- [x] `run_session(grinder_id, bean_id)` → main entry, in order:

```
1. check_warm()
2. get_env_data()
3. generate_recommendation()
4. purge shot (if setting changed ≥ 0.5)
5. log_first_shot(flow_time, taste)   ← full input
6. shots 2+: log_anomaly_shot() on anomaly only
7. update_database()
```

- [x] First shot: full input (flow + taste, both required)
- [x] Subsequent shots: anomaly only
- [x] Anomaly trigger: flow deviation > 3s OR taste ≠ 0 (excluding technique errors and intentional)

---

## 14. Anomaly log — `session.py`

- [x] `log_anomaly(shot_data, bean_id)` → `data/anomalies/{bean_id}.json`
- [x] Anomaly = genuine grind issue only (not technique error, not intentional)
- [x] `check_anomaly_pattern(bean_id)` → triggers at count ≥ 5
- [x] Anomaly data isolated from main training set

---

## 15. Output — `output.py`

- [x] `format_recommendation(...)` — full daily recommendation block
- [x] `format_warm_recommendation(adjustment)` — condensed WARM output
- [x] `format_stage_warning(stage)` — resting / declining alerts
- [x] `format_bootstrap_warning(shot_count, confidence)` — first 10 shots: generic parameters warning
- [x] `format_purge_notice(last_setting, new_setting)` — setting change → purge required
- [x] `format_anomaly_report(bean, count, patterns)` — pattern report

---

## 16. Learning phase — `session.py`

- [x] `get_learning_phase(shot_count)` → `"bootstrap"` / `"growing"` / `"mature"`

| Phase | Condition | Behaviour |
|-------|-----------|-----------|
| bootstrap | < 10 shots | Rule engine, full input required |
| growing | 10–50 shots | Pattern recognition begins |
| mature | ≥ 50 shots | Personalised, anomaly-only input |

- [x] At 10 shots: "Model is starting to personalise."
- [x] At 50 shots: "Mature phase. Anomaly-only input from here."
- [x] `count_total_shots()` excludes purge shots and technique errors

---

## 17. Canonical data formats

### Grinder profile `data/grinders/{name}.json`
```json
{
  "name": "EK43",
  "burr_type": "flat",
  "beta": 0.85,
  "total_kg": 12.5,
  "calibrated_at": "2026-04-01",
  "wear_alert_at_kg": 1000
}
```

### Bean profile `data/beans/{name}.json`
```json
{
  "name": "Ethiopia Yirgacheffe",
  "origin": "Ethiopia",
  "process": "washed",
  "roast_level": "light",
  "H": 1.2,
  "D": 1.0,
  "roast_date": "2026-03-20",
  "dose_g": 18,
  "yield_g": 36,
  "target_time_s": 28
}
```

### Session record `data/sessions/YYYY-MM-DD.json`
```json
{
  "date": "2026-04-01",
  "grinder": "EK43",
  "bean": "Ethiopia Yirgacheffe",
  "days_since_roast": 12,
  "temp": 22,
  "humidity": 65,
  "env_source": "api",
  "warm_state": "normal",
  "shots": [
    {
      "type": "dial",
      "setting": 11.5,
      "flow_time": 27,
      "taste": -1,
      "warm_weight": 1.0,
      "anomaly": false,
      "intentional": false,
      "technique_error": false
    }
  ],
  "recommendation": {
    "adjustment": -0.2,
    "confidence": 78
  }
}
```

### Personal vocab `data/vocab/personal.json`
```json
{
  "sharp":   -1,
  "bright":  -1,
  "harsh":    1,
  "bitter":   1,
  "clean":    0,
  "off today": "WARM_flag"
}
```

---

## Implementation rules

1. Every `[ ]` maps to a specific function or data file
2. Function names defined here — use them as-is
3. Data formats defined in Section 17 — do not add or remove fields
4. LLM layer does no numerical calculation — parsing and routing only
5. Purge shots, intentional shots, and technique errors are excluded from model training
6. All three exclusion types are excluded from the anomaly log
