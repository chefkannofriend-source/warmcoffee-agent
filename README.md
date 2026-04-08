# warmcoffee-agent

A coffee dialing assistant that learns your palate — not the SCA average.

Built for daily use with [Claude](https://claude.ai). Drop `CLAUDE.md` into a Claude project and it becomes your dialing partner.

---

## What it does

Every morning it asks three things: temperature, humidity, how you're feeling. It tells you exactly how many steps to adjust your grinder, what flow time to expect on the first shot, and how confident it is — based on your data, your machine, your water.

After 50 shots, the model stops using industry defaults and switches to coefficients fitted from your actual sessions. Nobody else can use your model, because your model contains you.

---

## The WARM system

The operator is the most expensive and least stable sensor in the dialing chain.

If you're sick, sleep-deprived, anxious, or have already had four coffees today — your palate is unreliable. WARM mode detects this with a single question at session start. Under WARM:

- Flow time data is logged at full weight
- Taste feedback is logged at 0.2 weight
- Grind adjustment is based on flow deviation only
- Output: *"Trust the numbers today, not the taste."*

Accumulated WARM records can reveal personal patterns — frequent triggers during allergy season, for example — and automatically reduce sensory weight during those periods.

---

## Architecture

**LLM does not do arithmetic. LLM writes the code that does arithmetic.**

```
User input (natural language)
        ↓
   Claude (CLAUDE.md)
   · parse variables
   · detect missing data
   · map taste vocabulary
   · classify WARM state
   · route to correct script
        ↓
   Python scripts
   · freshness decay (two-slope model)
   · temp / humidity offset
   · grind offset calculation
   · confidence score
   · quarterly personal formula
        ↓
   JSON data layer
   · sessions / grinders / beans / anomalies / vocab
        ↓
   Formatted output
   · recommendation + confidence + driver explanation
```

Every number you see came from a script. Claude never calculates — it routes.

---

## Setup

```bash
git clone https://github.com/YOUR_USERNAME/warmcoffee-agent.git
cd warmcoffee-agent
pip install -r requirements.txt
```

Copy the sample vocab and edit to match your taste language:
```bash
cp data/vocab/sample.json data/vocab/personal.json
```

Open a new [Claude project](https://claude.ai). Upload `CLAUDE.md` as a project instruction file, or paste its contents into the system prompt.

---

## First session

**1. Create your grinder profile**
```
python3 scripts/setup.py grinder "EK43" --burr flat
```

**2. Calibrate β coefficient** (5 minutes, 3 shots)

Claude will guide you through this conversationally. β is the grinder's sensitivity — how many seconds of flow change per step of adjustment. It varies between machines by 2×.

**3. Create a bean profile**
```
python3 scripts/setup.py bean "Ethiopia Yiru" \
  --origin "Ethiopia Yirgacheffe" \
  --process washed \
  --roast-level light \
  --roast-date 2026-04-01 \
  --dose 18 \
  --yield-g 36 \
  --target-time 28
```

**4. Cold start (3 days)**

For the first 3 days with a new bean, pull shots manually and report data conversationally. No recommendations yet — Claude is learning your baseline.

**5. Day 4 onwards: daily session**
```
# Before your first shot
python3 scripts/session.py recommend \
  --grinder "EK43" --bean "Ethiopia Yiru" \
  --temp 24 --humidity 68 --warm normal

# After pulling the shot
python3 scripts/session.py log \
  --grinder "EK43" --bean "Ethiopia Yiru" \
  --temp 24 --humidity 68 --warm normal \
  --setting 11.3 --flow-time 27 --taste "bright, clean"
```

---

## Constraints

```
Grinder profiles:  max 2
Bean profiles:     max 3
Combinations:      2 × 3 = 6 independent datasets
```

Each grinder × bean combination maintains its own data. Switching beans does not contaminate grinder data.

---

## Learning phases

| Phase | Shots | Behaviour |
|-------|-------|-----------|
| Bootstrap | < 10 | Generic parameters, full input required |
| Growing | 10–50 | Pattern recognition begins |
| Mature | ≥ 50 | Personal formula active, anomaly-only input |

At the mature phase, daily input is: temperature, humidity, flow time after first shot, WARM flag. That's it.

---

## Quarterly report

After 20+ shots in a quarter:
```
python3 scripts/gen_report.py --grinder "EK43" --bean "Ethiopia Yiru"
```

Report includes:
- Your taste baseline (average flavour score, direction)
- Flavour window calibrated to your actual data
- Seasonal lookup table (temp × humidity → starting setting)
- Personal formula with fitted coefficients (replaces industry defaults from next quarter)

---

## Known limitations

- **Environment data**: uses outdoor API or manual input as a proxy for grinder environment. Consistent source matters more than absolute accuracy.
- **β linearity**: calibrated at one setting, assumed linear. Large changes (> 2 steps) are directional, not precise.
- **Purge shot**: after a setting change ≥ 0.5 steps, pull one purge shot before the first learning shot. The system prompts this automatically.
- **Technique noise**: uneven distribution or inconsistent tamping affects flow independently of grind. Self-report `[t]` to exclude from training.
- **Bootstrap phase**: first 10 shots use generic H/D coefficients. Don't over-rely on early recommendations.

---

## File structure

```
warmcoffee-agent/
├── CLAUDE.md           ← agent instructions (load into Claude project)
├── spec.md             ← design specification
├── requirements.txt
├── data/
│   ├── beans/          ← bean profiles (auto-created)
│   ├── grinders/       ← grinder profiles (auto-created)
│   ├── sessions/       ← daily records (auto-created)
│   ├── anomalies/      ← anomaly log (auto-created)
│   ├── reports/        ← quarterly reports (auto-created)
│   └── vocab/
│       ├── sample.json     ← taste vocabulary template
│       └── personal.json   ← your vocab (gitignored)
└── scripts/
    ├── setup.py
    ├── calibrate.py
    ├── session.py
    ├── state.py
    ├── vocab.py
    ├── calc_freshness.py
    ├── calc_grind.py
    ├── calc_confidence.py
    ├── calc_ey.py
    ├── weather.py
    ├── output.py
    └── gen_report.py
```

---

## Design note

This is not a tool that makes you dial the "correct" espresso.

Correct espresso does not exist. The SCA gold cup is an average answer for everyone. What this gives you — after enough shots — is an answer tuned to your palate, your water, your machine, your state. Nobody else can use your model, because your model contains you.

Dialling is personal. This is your personal programme.
