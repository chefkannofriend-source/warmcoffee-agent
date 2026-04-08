# Coffee Dialing Agent — Design Specification

> Written: 2026-04-01
> Core principle: LLM reads language, scripts do math, data iterates, tool adapts to the person.

---

## 0. What this agent is an instance of

Restaurant cost calculation, coffee dialing, bread formula balancing — these three use cases are instances of the same framework:

```
Expert judgement → identify variables → mathematical formula → executable script → personalised iteration
```

This is not a coffee tool. It is the methodology of "turning any repetitive expert judgement into a learnable programme" applied to the coffee context. This is what "second brain" actually means.

---

## 1. Design principles

### Architecture
**LLM does not do arithmetic. LLM writes the code that does arithmetic.**

Flow: LLM understands input → encodes the mathematical logic as a formula → formula compiles to Python script → script runs the numbers → LLM interprets the result.

LLMs hallucinate on arithmetic. Let them write the calculation logic as code; code output is deterministic. 461.54 is always 461.54, not "around 46". The LLM is the author of the script, not the calculator.

### Human-first
The operator is the most expensive and least stable sensor in the dialing chain. The tool must adapt to human state — it cannot require the operator to be at peak condition to serve the tool. → **WARM system**

### Personalisation
Do not converge to SCA gold cup standards. Converge to your own optimum. Nobody else can use your model because your model contains your aesthetic judgement.

### Minimum input
At maturity, daily manual input must not exceed 3 items. Otherwise no one will keep using it.

---

## 2. Framework constraints

```
Grinder profiles:  max 2
Bean profiles:     max 3
Combinations:      2 × 3 = 6 independent data sets
```

Each combination maintains its own data, β coefficient, and decay curve. Switching beans does not contaminate the grinder data.

---

## 3. Data architecture

### 3.1 Grinder profile (set up once)

| Field | Description |
|-------|-------------|
| Name | User-defined (e.g. "EK43", "Niche Zero") |
| Burr type | flat / conical / ghost tooth |
| **β coefficient** | Grind sensitivity. Calibrated by test. Same 0.2-step adjustment can yield 2× different particle size change across grinder models. |
| Total kg ground | Tracks burr wear — alert at every 1,000 kg |

**β calibration (one-time, ~5 minutes):**
> Hold all other variables constant. Pull 3 shots, adjusting 0.5 steps finer each time. Record flow time for each. The script fits the grind-setting-to-flow-time response slope.

### 3.2 Bean profile (update on each new bag)

| Field | Unit | Description |
|-------|------|-------------|
| Origin / variety | text | Ethiopia Yirgacheffe / Gesha etc. |
| Process | washed / natural / honey / anaerobic | Affects density and moisture absorption |
| Roast level | light / medium-light / medium / medium-dark / dark | Maps to hardness coefficient H and density coefficient D |
| **Roast date** | YYYY-MM-DD | Baseline for all freshness calculations |
| Target dose | g | e.g. 18g |
| Target yield | g | e.g. 36g (1:2 ratio) |
| Target time | seconds | e.g. 28s |

### 3.3 Daily dynamic variables

| Variable | Source | Notes |
|----------|--------|-------|
| **Days since roast** | Auto-calculated | No manual input needed |
| **Room temperature** | Manual / weather API / sensor | 10°C swing ≈ 5–10 µm particle shift |
| **Relative humidity** | Same as above | Above 60%: beans absorb moisture, grind typically needs to go finer by 0.1–0.3 steps |
| **Last shot flow deviation** | Manual (±seconds) | Target 28s, actual 25s → enter −3 |
| **Taste flag** | Sour / balanced / bitter (−1 / 0 / +1) | Minimal — not free text |
| **WARM flag** | Normal / off today | See Section 6 |

**Environment data logic:**
```
User selects → [ Manual ]  [ Weather API (API key required) ]  [ Sensor (device config required) ]
Not configured → prompt for manual input
User skips → use yesterday's values, label "estimated", reduce confidence score
```

**Important:** Consistency of measurement source matters more than absolute accuracy. Mixing API data one day and manual guesses the next corrupts the correlation. Pick one source and stick with it.

### 3.4 Optional advanced variables

| Variable | Source | Value |
|----------|--------|-------|
| TDS (refractometer reading) | Refractometer | Accurate EY% calculation |
| Agtron colour value | Colour metre / visual estimate | More precise hardness baseline than roast level |
| Burr temperature | Infrared thermometer | During busy service burrs can reach 40–50°C, shifting particle distribution |
| Puck resistance | Decent and similar machines | Most accurate closed-loop data; limited hardware support |

---

## 4. Maths layer (script responsibility)

```python
# Days since roast
days_since_roast = today - roast_date

# Freshness decay — two-slope model
# Resting phase (≤7 days): rapid CO2 release, steep slope, parameters unstable
if days_since_roast <= 7:
    freshness_offset = f_early(days_since_roast)
else:
    freshness_offset = f_late(days_since_roast)  # gentle linear decline

# Extraction yield (requires TDS data)
EY_pct = (TDS_pct × yield_g) / dose_g × 100

# Brew ratio
brew_ratio = yield_g / dose_g

# Grind offset
grind_offset = β × (
    freshness_offset
    + temp_coefficient × (temp - temp_baseline)
    + humidity_coefficient × max(0, humidity - 60)
    + flow_correction(flow_deviation)
)

# Suggested setting
suggested_setting = last_setting + grind_offset
```

**Built-in coefficients (iterated from data over time):**

| Coefficient | Initial value | Description |
|-------------|---------------|-------------|
| H (hardness) | light=1.2 / medium=1.0 / dark=0.7 | Affects grind resistance |
| D (density) | washed=1.0 / natural=0.9 / anaerobic=1.1 | Affects moisture uptake and grind baseline |
| β | From calibration | Machine-specific sensitivity |

**Best flavour window (output daily with stage label):**

| Process | Window opens | Peak | Decline starts |
|---------|-------------|------|----------------|
| Washed | +7 days | +14 to +28 days | After +28 days |
| Natural | +14 days | +21 to +42 days | After +42 days |
| Honey / Anaerobic | +10 days | +18 to +35 days | After +35 days |

Daily output includes stage label:
```
[Resting]   Wait X more days — CO2 still releasing rapidly, parameters unstable
[Peak]      Currently in best flavour window
[Declining] X days past peak — consider dialling finer, or finish the bag soon
```

---

## 5. Known model limitations

These are real limitations of the mathematical model. Understanding them prevents over-relying on early recommendations.

### 5.1 Environment data accuracy
The system uses temperature and humidity as *relative corrections*, not absolute physical constants. Outdoor API data ≠ indoor grinder environment. This is acceptable as long as the user uses a consistent measurement source — the β coefficient will absorb systematic offsets over time. Mixing sources introduces random noise that is much worse than a consistent systematic bias.

### 5.2 Bean variable approximation
H and D coefficients are bucketed by roast level and process method. Two light-roast washed Ethiopians from different farms/varieties can behave differently. The early recommendations (bootstrap phase, <10 shots) use generic parameters. Personalisation develops after ~20 shots from real feedback. **Do not over-rely on bootstrap-phase output.**

### 5.3 Grinder non-linearity
β calibration captures the local linear response near the calibration setting. Response may be non-linear across a wide range. For large setting changes (>2 steps), treat the prediction as directional, not precise.

### 5.4 Residual grounds (purge shot)
After a grind setting change, the first 1–2 shots contain a mix of old and new particle sizes. The system handles this by:
- Detecting setting changes ≥ 0.5 steps
- Prompting a purge shot before the first learning shot
- Excluding purge shot flow data from model training
- Discarding the previous session's flow deviation when the setting has changed (stale data from a different grind size)

### 5.5 Technique noise
Uneven distribution, inconsistent tamping, portafilter moisture, and channelling all affect flow time independently of grind setting. The system cannot distinguish technique errors from grind errors purely from flow data. Users must self-report:
- **[g] grind issue**: used for model training
- **[t] technique error**: logged but excluded from grind model

### 5.6 Flavour-priority decisions
Expert baristas deliberately deviate from target parameters for specific flavour profiles. The system allows users to mark a shot as intentional:
- Intentional shots are logged for reference but **not used for training**
- The model will not attempt to "correct" intentional deviations back toward target

---

## 6. WARM system

### What WARM is
Acknowledges that the operator is a critical and variable sensor in the feedback loop. During illness, injury, emotional disruption, or extreme fatigue, sensory feedback is unreliable and should not drive grind adjustments.

### Trigger reference

| Category | Examples | Sensory effect |
|----------|---------|----------------|
| Physical | Cold / blocked nose / allergy | Reduced olfaction, dulled perception |
| Physical | Mouth injury / recent dental work | Local pain interferes with taste |
| Physical | Severe sleep deprivation | Elevated bitterness threshold, reduced sweetness |
| Physical | Extreme hunger | Acidity and bitterness amplified |
| Physical | Heavy food within 30 min | Palate baseline polluted |
| Emotional | Anxiety / high stress / argument | Bitterness perception amplified |
| Emotional | Extreme elation | Hedonic bias, tendency to over-rate |
| Environmental | 4+ coffees already today | Taste fatigue, broad dulling |

### WARM input
One question at session start:
> "How are you feeling today?"
> `Normal` / `Off today`

Optional: one line of context. Not required.

### System behaviour under WARM

```
Objective data (time, dose, yield)   → logged normally, weight 1.0
Sensory feedback (taste flag)        → logged, weight reduced to 0.2
Grind recommendation                 → flow deviation only, no sensory-driven adjustment
Output message                       → "Trust the numbers today, not the taste."
```

### Long-term WARM value
Accumulated WARM records can reveal personal patterns — e.g. frequent WARM triggers during seasonal change → automatically increase objective data weight and reduce sensory participation during that period.

---

## 7. Daily session flow

```
Start dialling
│
├─ WARM check (1 question)
│
├─ Environment confirmation
│   Temp + humidity: auto-fetch / manual / yesterday's estimate
│
├─ System outputs today's recommendation (see Section 8)
│
├─ Purge shot (if setting changed ≥ 0.5 steps)
│   Run one shot to flush residuals — flow logged, excluded from model
│
├─ First real shot (full input required)
│   Log: actual flow time + taste flag
│   → If flow deviation > 3s: was this [g] grind or [t] technique?
│   → If taste ≠ balanced: was this [intentional] or [unexpected]?
│
├─ Shots 2+: only log on anomaly
│   Normal flow + balanced taste → no input needed
│   Anomaly → log flow + taste + cause
│
└─ System updates database, generates next-session baseline
```

---

## 8. Output format

```
── Today's recommendation ──
Bean:    Ethiopia Yirgacheffe  ·  Day 18 post-roast  [Peak]
Grinder: EK43

Grind adjustment: finer 0.2 steps
→ Yesterday 11.5  →  Today 11.3

Predicted first shot: 25–31s  (target 28s)
Confidence: 82%  (based on last 7 shots)

Main drivers: humidity rose to 68% (+0.15 steps) · day 18 ageing (+0.08 steps)

---
Report actual time after your first shot.
```

**Under WARM:**
```
── Today's recommendation · WARM mode ──
Go finer by 0.1  →  setting 11.4

Trust the numbers today, not the taste.
Report flow time after first shot.
```

---

## 9. Learning phases

| Phase | Condition | Behaviour | Daily input |
|-------|-----------|-----------|-------------|
| **Bootstrap** | < 10 shots | Rule-based engine, generic parameters | Full (5–7 items) |
| **Growing** | 10–50 shots | Pattern recognition begins, can infer some variables | Reduced (3–4 items) |
| **Mature** | 50+ shots | Personalised model, anomaly-only input | Minimal (2 items + anomalies) |

**Mature phase minimum input:**
- Days since roast (auto)
- Temp + humidity (API / sensor / manual)
- Flow deviation (1 number)
- WARM flag (1 tap)

---

## 10. Technical architecture

```
User input (natural language / structured form)
        ↓
   LLM parsing layer
   · extract variables
   · detect missing data
   · map taste vocabulary (see Section 11)
   · classify WARM state
   · route to correct flow node
        ↓
   Python script layer
   · freshness decay (two-slope function)
   · temperature / humidity offset
   · grind_offset calculation
   · EY% (when TDS available)
   · confidence score
        ↓
   Data layer (JSON)
   · per-session shot archive
   · anomaly log (separate)
   · WARM log (separate)
   · grinder profiles / bean profiles
        ↓
   Output layer
   · today's recommendation
   · confidence score
   · main driver explanation
   · stage label and warning
```

---

## 11. Taste vocabulary mapping

Every person describes taste differently. "Bright", "sharp", "clean", "off today" — these may mean the same thing to one person and different things to another.

**Mapping flow:**

```
Cold start (3 days):
  User says new word → agent asks: "When you say 'bright' — sour/bright or bitter/harsh?"
  User confirms → stored in personal vocab: { "bright": -1 }
  Same word next time → mapped directly, no question

Mature phase:
  Personal vocab is stable, agent maps directly
  New word encountered → ask again, update vocab
```

**Personal vocab example:**
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

Vocab is user-specific. The same word can map in opposite directions for different people. No shared default dictionary.

---

## 12. What this agent is

Not a tool that makes you dial the "correct" espresso.

Correct espresso does not exist. The SCA gold cup is an average answer for everyone.

What this agent gives you — after enough shots — is an answer tuned to your palate, your water, your machine, your bean, your state. Nobody else can use your model, because your model contains you.

Dialling is mysticism. Use it long enough, and you'll have your own mysticism programme.
