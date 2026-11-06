"""SyllabusAI parser wrapper.

Primary path: the C++ parser binary (parser_cpp/syllabus_parser.cpp),
invoked as a subprocess — it reads syllabus text on stdin and prints one
JSON object. The binary path comes from SYLLABUS_PARSER_BIN, defaulting to
the compiled binary next to this package.

Fallback path: if the binary is missing or fails, a small pure-Python
extractor (same JSON shape, simpler heuristics) runs instead, so the service
degrades instead of dying. The C++ parser is the parser of record; the
fallback exists only for resilience.
"""

from __future__ import annotations

import json
import os
import re
import subprocess

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _binary_path() -> str | None:
    env = os.environ.get("SYLLABUS_PARSER_BIN")
    candidates = [env] if env else []
    here = os.path.dirname(os.path.abspath(__file__))
    candidates += [
        os.path.join(here, "..", "parser_cpp", "syllabus_parser"),
        os.path.join(here, "..", "syllabus_parser"),
        "/app/syllabus_parser",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def parse_with_cpp(text: str) -> dict | None:
    """Run the C++ parser. Returns parsed dict, or None if unavailable."""
    binary = _binary_path()
    if not binary:
        return None
    try:
        proc = subprocess.run(
            [binary], input=text.encode("utf-8"), capture_output=True, timeout=20
        )
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout.decode("utf-8"))
    except Exception:
        return None


# ---------------- pure-Python fallback (same JSON shape) ----------------

_HEADING_KWS = [
    "course description", "learning objectives", "required materials",
    "materials", "textbook", "grading", "grade breakdown", "assessment",
    "artificial intelligence", "ai policy", "generative ai", "late work",
    "late policy", "slip days", "schedule", "key dates", "important dates",
    "academic integrity", "attendance",
]


def _sections(text: str):
    sections, cur_h, buf = [], "", []
    for raw in text.splitlines():
        line = raw.strip()
        low = line.lower()
        head = None
        if line.startswith("#"):
            head = line.lstrip("#").strip()
        elif line and line[0] not in "-*•" and len(line) <= 70:
            if line.endswith(":") and "as follows" not in low and "will be able" not in low:
                head = line[:-1]
            elif line.isupper() and len(line) >= 4:
                head = line
            else:
                for k in _HEADING_KWS:
                    if "%" in line:
                        break  # a percentage line is data, not a heading
                    if k in low and len(line) <= len(k) + 25:
                        head = line
                        break
        if head is not None:
            sections.append({"heading": cur_h, "text": "\n".join(buf)})
            cur_h, buf = head, []
        else:
            buf.append(raw)
    sections.append({"heading": cur_h, "text": "\n".join(buf)})
    return [s for s in sections if s["heading"] or s["text"].strip()]


def _find_section(sections, keywords):
    for s in sections:
        if any(k in s["heading"].lower() for k in keywords):
            return s
    return None


def parse_with_python(text: str) -> dict:
    sections = _sections(text)
    all_text = "\n".join(s["heading"] + "\n" + s["text"] for s in sections)

    code = title = instructor = term = ""
    m = re.search(r"\b([A-Z]{2,4}\s*\d{3,4}[A-Z]?)\s*[:\-]\s*(.+)", text)
    if m:
        code, title = m.group(1).strip(), m.group(2).strip()[:80]
    m = re.search(r"Instructor\s*:\s*(.+)", text, re.I)
    if m:
        instructor = m.group(1).strip()
    m = re.search(r"(Fall|Spring|Summer|Winter)\s+(20\d{2})", text, re.I)
    if m:
        term = f"{m.group(1)} {m.group(2)}"

    ai_text, stance, found = "", "not_stated", False
    s = _find_section(sections, ["artificial intelligence", "ai policy", "generative ai"])
    if s and s["text"].strip():
        ai_text, found = s["text"].strip(), True
    if found:
        low = ai_text.lower()
        allows = any(w in low for w in ["may be used", "may use", "allowed", "permitted", "you may"])
        restricts = any(w in low for w in ["may not", "not permitted", "prohibited", "not allowed", "must not"])
        stance = ("allowed_with_rules" if allows and restricts else
                  "prohibited" if restricts else "allowed" if allows else "unclear")
    quotes = []
    if found:
        for sent in re.split(r"(?<=[.!?])\s+", ai_text.replace("\n", " ")):
            sl = sent.lower()
            if "must" in sl or "may not" in sl or "disclosure" in sl:
                quotes.append(sent.strip())
            if len(quotes) >= 2:
                break

    grading, total = [], 0
    s = _find_section(sections, ["grading", "grade breakdown", "assessment"])
    scope = s["text"] if s else all_text
    for ln in scope.splitlines():
        ll = ln.lower()
        if any(w in ll for w in ["per day", "late", "lose"]):
            continue
        m = re.search(r"^\s*[-•*]?\s*([A-Za-z][A-Za-z0-9 &/'\-()]{2,70}?)\s*[:\-]\s*(\d{1,3})\s*%", ln)
        if m:
            label = re.sub(r"\s*\(\d+\s+total\)\s*$", "", m.group(1).strip())
            pct = int(m.group(2))
            if 0 <= pct <= 100 and all(g["label"].lower() != label.lower() for g in grading):
                grading.append({"label": label, "percent": pct})
                total += pct

    slip_count, slip_text, slip_found = -1, "", False
    m = re.search(r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+slip\s+days?",
                  all_text, re.I)
    if m:
        raw = m.group(1).lower()
        slip_count = int(raw) if raw.isdigit() else _WORD_NUM.get(raw, -1)
        slip_found = slip_count >= 0
    if slip_found:
        sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", all_text.replace("\n", " ")) if "slip" in x.lower()]
        slip_text = " ".join(sents)[:900]

    late_text, late_found = "", False
    s = _find_section(sections, ["late work", "late policy", "slip days"])
    if s and s["text"].strip():
        late_text, late_found = s["text"].strip()[:1200], True

    date_re = re.compile(
        r"(January|February|March|April|May|June|July|August|September|Sept\.?|"
        r"October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|"
        r"Aug\.?|Oct\.?|Nov\.?|Dec\.?)\s+(\d{1,2})(?:\s*[-–—]\s*(\d{1,2}))?(?:,\s*(\d{4}))?",
        re.I)
    deadlines, seen = [], set()
    sched = _find_section(sections, ["schedule", "key dates", "important dates", "calendar"])
    cand = sched["text"].splitlines() if sched else []
    for ln in text.splitlines():
        ll = ln.lower()
        if any(w in ll for w in ["due", "exam", "midterm", "final"]) and date_re.search(ln):
            if ln not in cand:
                cand.append(ln)
    for ln in cand:
        if "no assignment due" in ln.lower() or "no class" in ln.lower():
            continue
        m = date_re.search(ln)
        if not m:
            continue
        date_raw = m.group(0)
        mo = _MONTHS.get(m.group(1).lower().rstrip("."), 0)
        day = int(m.group(2))
        year = m.group(4) or ""
        date_norm = f"{year}-{mo:02d}-{day:02d}" if mo and year else ""
        label = ln.replace(date_raw, "")
        label = re.sub(r"^\s*[-•*]\s*", "", label)
        label = re.sub(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*", "", label, flags=re.I)
        label = re.sub(r"(,?\s*\d{1,2}:\d{2}\s*(AM|PM|am|pm)?\.?)\s*$", "", label)
        label = re.sub(r",\s*,", ",", label)
        label = re.sub(r"\s+", " ", label).strip()
        while label and label[-1] in ",.:;-":
            label = label[:-1].strip()
        if ":" in label:
            label = label.split(":", 1)[0].strip()
        kl = (label + " " + ln).lower()
        kind = ("midterm" if "midterm" in kl else "final_project" if "final project" in kl
                else "final_exam" if "final exam" in kl else "final" if "final" in kl
                else "quiz" if "quiz" in kl else "proposal" if "proposal" in kl
                else "presentation" if "presentation" in kl
                else "homework" if ("homework" in kl or "assignment" in kl)
                else "project" if "project" in kl else "exam" if "exam" in kl else "other")
        key = (label, date_raw)
        if key not in seen:
            seen.add(key)
            deadlines.append({"label": label, "date_raw": date_raw, "date": date_norm,
                              "kind": kind, "context": ln.strip()})

    materials = []
    s = _find_section(sections, ["required materials", "materials", "textbook", "readings"])
    if s:
        for ln in s["text"].splitlines():
            t = re.sub(r"^\s*[-•*]\s*", "", ln).strip()
            if len(t) >= 3:
                materials.append(t)

    return {
        "course": {"code": code, "title": title, "instructor": instructor, "term": term},
        "ai_policy": {"found": found, "stance": stance, "text": ai_text[:2000], "quotes": quotes},
        "grading": {"items": grading, "total": total},
        "slip_days": {"found": slip_found, "count": slip_count, "text": slip_text},
        "late_policy": {"found": late_found, "text": late_text},
        "deadlines": deadlines,
        "materials": materials,
        "sections": [{"heading": s["heading"], "text": s["text"][:1500]}
                     for s in sections if s["heading"]],
    }


def parse(text: str) -> tuple[dict, str]:
    """Parse syllabus text. Returns (parsed_dict, engine_used)."""
    result = parse_with_cpp(text)
    if result is not None:
        return result, "cpp"
    return parse_with_python(text), "python-fallback"
