"""
ehr_parser.py  -  Reads one patient .txt file and splits it by SECTION (not by
character count), so every chunk keeps its header ("who + what section").

parse_patient_file(path) returns:
  chunks : list of {"text", "metadata"}  -> these get embedded into index
  record : dict with sections + visit numbers -> used by the exact-answer tools
  flags  : list of data-quality warnings
"""
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

# Matches lines like:  ALLERGIES | Ms. Maximina Langosh | ID 0aed8a17
HEADER_RE = re.compile(r"^([A-Z][A-Z &]+(?: \([^)]*\))?) \| (.+?) \| ID (\S+)$")
# Matches visit lines like:  [Name | ID x] 2020-01-18: BP 43.3/41.4 mmHg
VISIT_RE = re.compile(r"^\[.*?\]\s*(\d{4}-\d{2}-\d{2}):\s*(.*)$")
# Matches pieces like:  "Heart rate 94 /min"  "BP 120/70 mmHg"
METRIC_RE = re.compile(r"^(BP|Height|Weight|BMI|Heart rate|Resp rate|Hemoglobin)\s+([\d./]+)\s*(.*)$")

MAX_CHARS = 1200  # a section longer than this is split by bullet lines


def _split_sections(lines) -> Iterator[Tuple[str, str, str, List[str]]]:
    """Yield (section, patient name, patient id, body lines) for every section header found."""
    header: Optional[Tuple[str, str, str]] = None
    body: List[str] = []
    for raw in lines:
        line = raw.rstrip()
        if not line:
            continue
        m = HEADER_RE.match(line)
        if m:
            if header:
                yield (*header, body)
            header = (m.group(1).strip(), m.group(2).strip(), m.group(3))
            body = []
        elif header:
            body.append(line)
    if header:
        yield (*header, body)


def _pack_bullets(header, body, max_chars):
    chunks, buf = [], []
    for line in body:
        if buf and len("\n".join([header] + buf + [line])) > max_chars:
            chunks.append("\n".join([header] + buf))
            buf = []
        buf.append(line)
    if buf:
        chunks.append("\n".join([header] + buf))
    return chunks


def _parse_visit(date, rest):
    entry = {"date": date}
    for part in rest.split(";"):
        m = METRIC_RE.match(part.strip())
        if not m:
            continue
        key, val, _unit = m.groups()
        key = key.lower().replace(" ", "_")
        if key == "bp":
            s, d = (float(x) for x in val.split("/"))
            entry["bp_systolic"], entry["bp_diastolic"] = s, d
        else:
            entry[key] = float(val)
    return entry


def bp_is_implausible(sys_, dia):
    return sys_ < dia or sys_ < 70 or sys_ > 250 or dia < 30 or dia > 150


def parse_patient_file(path) -> Dict[str, Any]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    chunks, flags = [], []
    record: Dict[str, Any] = {"visits": [], "sections": {}}

    for section, name, pid, body in _split_sections(lines):
        header = f"{section} | {name} | ID {pid}"
        record.update(patient_name=name, patient_id=pid)
        record["sections"][section] = body
        meta = {"patient_id": pid, "patient_name": name,
                "section": section, "source": Path(path).name}

        if section.startswith("PATIENT SUMMARY"):
            for line in body:
                for token in line.split(" | "):
                    if ":" in token:
                        k, v = token.split(":", 1)
                        record[k.strip().lower()] = v.strip()

        if section.startswith("VISIT HISTORY"):
            for line in body:
                m = VISIT_RE.match(line)
                if not m:
                    continue
                date, rest = m.groups()
                visit = _parse_visit(date, rest)
                record["visits"].append(visit)
                if "bp_systolic" in visit and bp_is_implausible(visit["bp_systolic"], visit["bp_diastolic"]):
                    flags.append(f"{date}: blood pressure {visit['bp_systolic']:g}/{visit['bp_diastolic']:g} looks implausible")
                chunks.append({"text": f"{header}\n{date}: {rest}",
                               "metadata": {**meta, "date": date}})
            continue

        for text in _pack_bullets(header, body, MAX_CHARS):
            chunks.append({"text": text, "metadata": meta})

    record["visits"].sort(key=lambda v: v["date"])
    record["flags"] = flags
    return {"chunks": chunks, "record": record, "flags": flags}
