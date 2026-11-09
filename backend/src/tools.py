"""
tools.py  -  Exact-answer tools. They use plain Python on the structured
record, so there is NO guessing by the AI model.

  calculate(query, record) -> BMI or weight-based dose
  lookup(record, query)    -> prints a whole section (allergies, meds, ...)
  trend(record, query)     -> values over time for vitals (weight, BMI, BP...)
"""
import re
from src.ehr_parser import bp_is_implausible

LBS_TO_KG = 0.45359237


# ---------------------------------------------------------------- helpers
def _section(record, prefix):
    for name, lines in record.get("sections", {}).items():
        if name.startswith(prefix):
            return name, lines
    return None, []


def _latest_weight_height(record):
    for v in reversed(record.get("visits", [])):
        if "weight" in v and "height" in v:
            return v["weight"], v["height"], v["date"]
    return None, None, None


# ------------------------------------------------------------- calculator
def _find_weight_kg(q):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|kilograms?|lbs?|pounds?)\b", q)
    if not m:
        return None
    val = float(m.group(1))
    return val * LBS_TO_KG if m.group(2).startswith(("lb", "pound")) else val


def _find_height_m(q):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(cm|centimet\w+|meters?|metres?|m)\b", q)
    if not m:
        return None
    val = float(m.group(1))
    return val / 100 if m.group(2).startswith("c") else val


def _bmi_category(bmi):
    if bmi < 18.5:
        return "underweight"
    if bmi < 25:
        return "normal weight"
    if bmi < 30:
        return "overweight"
    return "obesity"


def calculate(query, record=None):
    q = query.lower()
    weight = _find_weight_kg(q)

    # weight-based dose, e.g. "dose for 15 mg/kg for a 20 kg patient"
    dose = re.search(r"(\d+(?:\.\d+)?)\s*mg\s*/\s*kg", q)
    if dose:
        if weight is None and record:
            weight = _latest_weight_height(record)[0]
        if weight is None:
            return "I need the patient's weight (for example '20 kg') to calculate a dose."
        per_kg = float(dose.group(1))
        return (f"Dose = {per_kg:g} mg/kg x {weight:g} kg = {per_kg * weight:g} mg.\n"
                "Calculated with Python, not by the AI. A clinician or pharmacist must verify the dose.")

    if "bmi" in q or "body mass" in q:
        height_m = _find_height_m(q)
        note = ""
        if (weight is None or height_m is None) and record:
            w, h, date = _latest_weight_height(record)
            if w is not None and h is not None:
                weight = weight if weight is not None else w
                height_m = height_m if height_m is not None else h / 100
                note = f" (missing values taken from the record dated {date})"
        if weight is None or height_m is None:
            return "To calculate BMI I need both weight and height, e.g. '80 kg and 175 cm'."
        bmi = weight / (height_m ** 2)
        return (f"BMI = {weight:g} kg / ({height_m:g} m)^2 = {bmi:.1f} kg/m2 -> {_bmi_category(bmi)}{note}.\n"
                "Calculated with Python, not by the AI.")

    return "I can calculate BMI or a weight-based dose (mg/kg). Please include the numbers and units."


# ------------------------------------------------------------ dosing questions
# This assistant NEVER recommends a dose. For a dosing question it (1) says so, (2) shows what the
# patient's record says about the drug if it is there, and (3) offers the mg/kg arithmetic.
DOSE_RE = re.compile(r"\bdos(?:e|es|ed|age|ages|ing)\b|\bhow (?:much|many)\b.{0,40}\b(?:give|take|administer|prescribe|needed|required)\b")

_NOT_DRUG_WORDS = {
    "dosage", "dosages", "doses", "dosing", "patient", "patients", "should", "required", "require", "recommended",
    "recommend", "prescribed", "prescribe", "currently", "medication", "medications", "medicine", "weight",
    "appropriate", "amount", "would", "which", "there", "their", "about", "please", "tablet", "tablets", "injection",
    "daily", "weekly", "maximum", "minimum", "normal", "usual", "standard", "adult", "adults", "child", "children",
    "elderly", "kidney", "renal", "liver", "hepatic", "taking", "given", "record", "recorded", "needed", "tell",
}

POLICY_FULL = ("I can't recommend a dose. The right dose depends on the drug, the reason it is used, the patient's age, "
               "kidney and liver function, and other medicines, so it should come from a prescribing reference "
               "(a formulary or the drug's official label) or a pharmacist.")
POLICY_SHORT = ("This is what the record says, not a dosing recommendation. Doses should come from a prescribing "
                "reference or a pharmacist.")


def is_dose_question(query):
    return bool(DOSE_RE.search(query.lower()))


def _drug_candidates(query, skip):
    words = re.findall(r"[a-z][a-z-]{5,}", query.lower())
    return [w for w in words if w not in _NOT_DRUG_WORDS and w not in skip]


def dose_answer(record, query, patient_label=None, patient_named=False):
    """Return (text, sources). `record` may be None (no patient). Never invents a dose."""
    skip = set()
    meds = []                                   # (section name, line) pairs from the patient's record
    if record:
        skip = {w for w in re.sub(r"[^a-z ]", " ", record.get("patient_name", "").lower()).split()}
        for prefix in ("CURRENT MEDICATIONS", "PAST MEDICATIONS"):
            name, lines = _section(record, prefix)
            meds += [(name, line) for line in lines] if name else []
    candidates = _drug_candidates(query, skip)

    matched = [(n, l) for n, l in meds if any(c in l.lower() for c in candidates)]
    weight = _find_weight_kg(query.lower())
    parts, sources = [], []

    if matched:
        shown = "\n".join(f"{'Current' if n.startswith('CURRENT') else 'Past'}: {l.lstrip('- ').strip()}" for n, l in matched)
        parts.append(f"Recorded for {patient_label}:\n{shown}")
        sources = list(dict.fromkeys(n for n, _ in matched))
        parts.append(POLICY_SHORT)
    else:
        if record and patient_named and candidates:
            parts.append(f"No medication matching \"{max(candidates, key=len)}\" appears in {patient_label}'s record.")
        elif record and patient_named and not candidates:
            name, lines = _section(record, "CURRENT MEDICATIONS")
            if name:
                parts.append(f"Current medications recorded for {patient_label}:\n" + "\n".join(lines))
                sources = [name]
        parts.append(POLICY_FULL)
        if weight is not None:
            parts.append(f"A weight alone ({weight:g} kg) does not give a dose. If your reference states a dose per "
                         f"kilogram, tell me the mg/kg value and I will calculate the total with Python, for example "
                         f"\"Calculate N mg/kg for {weight:g} kg\", replacing N with the number from your reference.")
    return "\n\n".join(parts), sources


# ------------------------------------------------------------------ lookup
LAST_VISIT_RE = re.compile(r"(last|latest|most recent|recent) (visit|appointment|encounter|checkup)|last seen")


def format_visit(v):
    parts = []
    if "bp_systolic" in v:
        parts.append(f"BP {v['bp_systolic']:g}/{v['bp_diastolic']:g} mmHg")
    for key, label, unit in [("heart_rate", "Heart rate", "/min"), ("resp_rate", "Resp rate", "/min"),
                             ("weight", "Weight", "kg"), ("height", "Height", "cm"),
                             ("bmi", "BMI", "kg/m2"), ("hemoglobin", "Hemoglobin", "g/dL")]:
        if key in v:
            parts.append(f"{label} {v[key]:g} {unit}")
    return f"{v['date']}: " + "; ".join(parts)


DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
VISIT_WORDS_RE = re.compile(r"visit|vitals|reason|seen|appointment|check-?up|encounter|measured|recorded")


def visit_on_date(record, query):
    """Answer 'what happened on <date>' from the visit list. Returns (text, sources) or (None, [])."""
    m = DATE_RE.search(query)
    if not m or not VISIT_WORDS_RE.search(query.lower()):
        return None, []
    date = m.group(1)
    for v in record.get("visits", []):
        if v["date"] == date:
            text = f"Visit on {date}:\n{format_visit(v)}"
            if re.search(r"reason|why", query.lower()):
                text += "\n(The record lists measurements only; it states no reason for the visit.)"
            return text, ["VISIT HISTORY"]
    return f"No visit is recorded on {date}.", ["VISIT HISTORY"]


def is_date_visit_question(query):
    return bool(DATE_RE.search(query) and VISIT_WORDS_RE.search(query.lower()))


def is_overview(query):
    """'Tell me about X' style questions: short, and asking for the whole picture."""
    q = query.lower()
    return bool(re.search(r"tell me about|overview|who is|profile|everything", q)) and len(q.split()) <= 8


def lookup(record, query):
    """Return (text, [section names]) or (None, []) if nothing matches."""
    q = query.lower()
    text, src = visit_on_date(record, query)
    if text:
        return text, src
    if LAST_VISIT_RE.search(q) and record.get("visits"):
        return "Most recent visit on record:\n" + format_visit(record["visits"][-1]), ["VISIT HISTORY"]
    wants_past = bool(re.search(r"\b(past|previous|former|resolved|history|all)\b", q))
    wanted = []  # list of section-name prefixes
    if is_overview(q):
        wanted += ["PATIENT SUMMARY", "ACTIVE CONDITIONS", "CURRENT MEDICATIONS", "ALLERGIES", "LATEST VITALS"]

    if "allerg" in q:
        wanted.append("ALLERGIES")
    if re.search(r"medication|medicine|\bdrugs?\b|prescri", q):
        wanted.append("CURRENT MEDICATIONS")
        if wants_past:
            wanted.append("PAST MEDICATIONS")
    if re.search(r"condition|diagnos|problem", q):
        wanted.append("ACTIVE CONDITIONS")
        if wants_past:
            wanted.append("RESOLVED CONDITIONS")
    if re.search(r"latest|most recent|vitals|\blabs?\b", q):
        wanted.append("LATEST VITALS")
    if re.search(r"summary|\bdob\b|\bage\b|born|gender|status|deceased|alive", q):
        wanted.append("PATIENT SUMMARY")

    wanted = list(dict.fromkeys(wanted))   # remove duplicates, keep order
    parts, used = [], []
    for prefix in wanted:
        name, lines = _section(record, prefix)
        if name:
            parts.append(name.split(" (")[0].title() + ":\n" + "\n".join(lines))
            used.append(name)
    if not parts:
        return None, []
    return "\n\n".join(parts), used


# ------------------------------------------------------------------- trend
METRICS = [  # (label, search words, record key, unit)
    ("Blood pressure", ["blood pressure", "bp"], "bp", "mmHg"),
    ("BMI", ["bmi", "body mass index"], "bmi", "kg/m2"),
    ("Weight", ["weight"], "weight", "kg"),
    ("Height", ["height"], "height", "cm"),
    ("Heart rate", ["heart rate", "pulse"], "heart_rate", "/min"),
    ("Respiratory rate", ["respiratory", "resp rate", "breathing rate"], "resp_rate", "/min"),
    ("Hemoglobin", ["hemoglobin", "haemoglobin"], "hemoglobin", "g/dL"),
]


def metrics_in(query):
    q = query.lower()
    return [m for m in METRICS if any(re.search(rf"\b{re.escape(w)}\b", q) for w in m[1])]


def _year_filter(query):
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", query)]
    q = query.lower()
    if len(years) >= 2:
        return min(years), max(years)
    if len(years) == 1:
        if re.search(r"since|after|from", q):
            return years[0], 9999
        return years[0], years[0]
    return 0, 9999


def metrics_by_label(labels):
    """['Weight', 'BMI'] -> the matching METRICS entries (used for follow-up questions)."""
    return [m for m in METRICS if m[0] in labels]


def trend(record, query, metrics=None):
    """Return (text, ['VISIT HISTORY']) or (None, []).
    `metrics` lets a follow-up question reuse the vital sign from the previous question."""
    chosen = metrics or metrics_in(query)
    if not chosen:
        return None, []
    lo, hi = _year_filter(query)
    visits = [v for v in record.get("visits", []) if lo <= int(v["date"][:4]) <= hi]
    exact = DATE_RE.search(query)
    if exact:                                   # a full date like 2025-04-25 means that day only
        visits = [v for v in record.get("visits", []) if v["date"] == exact.group(1)]
    blocks = []

    for label, _words, key, unit in chosen:
        rows = []
        for v in visits:
            if key == "bp":
                if "bp_systolic" in v:
                    s, d = v["bp_systolic"], v["bp_diastolic"]
                    warn = "  (looks implausible - possible data error)" if bp_is_implausible(s, d) else ""
                    rows.append((v["date"], f"{s:g}/{d:g} {unit}{warn}", None))
            elif key in v:
                rows.append((v["date"], f"{v[key]:g} {unit}", v[key]))
        if not rows:
            blocks.append(f"{label}: no recorded values for that period.")
            continue
        lines = [f"{label} over time:"] + [f"  {d}: {txt}" for d, txt, _ in rows]
        nums = [(d, n) for d, _t, n in rows if n is not None]
        if len(nums) >= 2:
            (d0, a), (d1, b) = nums[0], nums[-1]
            lines.append(f"  Change: {a:g} ({d0}) -> {b:g} ({d1}) = {b - a:+.1f} {unit}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks), ["VISIT HISTORY"]