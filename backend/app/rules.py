"""SyllabusAI rules engine.

Design mirror: this is the "OCaml rules engine" half of the SyllabusAI
architecture, implemented in Python so the service can run and be verified
in this environment (OCaml is not installed here and cannot be installed).
Each rule is a pure function over the parser's JSON: it matches on parsed
facts and produces a finding with a severity, a plain-language takeaway,
and the evidence it is based on. A future OCaml port would keep these same
rule names, the same input shape, and the same finding shape.

Rule names: AI_POLICY, GRADING, SLIP_DAYS, LATE_POLICY, DEADLINES,
MATERIALS. VERDICT composes the findings into "what this means for you".
"""

from __future__ import annotations

import re
from datetime import date

SEVERITY_ORDER = {"flag": 0, "watch": 1, "info": 2}


def _finding(rule, severity, title, takeaway, evidence=""):
    return {"rule": rule, "severity": severity, "title": title,
            "takeaway": takeaway, "evidence": evidence}


def rule_ai_policy(parsed):
    ai = parsed.get("ai_policy", {})
    if not ai.get("found"):
        return _finding("AI_POLICY", "watch",
                        "No AI policy found in this syllabus",
                        "The syllabus never says whether AI tools are allowed. "
                        "Ask the instructor before using ChatGPT or similar tools "
                        "on coursework — an unstated policy is not permission.")
    stance = ai.get("stance", "unclear")
    quotes = ai.get("quotes") or []
    evidence = quotes[0] if quotes else ai.get("text", "")[:300]
    if stance == "prohibited":
        return _finding("AI_POLICY", "flag",
                        "AI tools are not allowed in this class",
                        "Do not use generative AI on coursework here — the syllabus "
                        "bans it, and a violation counts as an academic integrity "
                        "case.", evidence)
    if stance == "allowed_with_rules":
        return _finding("AI_POLICY", "watch",
                        "AI is allowed, but only with rules",
                        "You can use AI for brainstorming and outlining, but you "
                        "must disclose it and you may not submit AI-generated text "
                        "as your own work. Read the full policy before your first "
                        "assignment.", evidence)
    if stance == "allowed":
        return _finding("AI_POLICY", "info",
                        "AI tools are allowed",
                        "The syllabus permits AI use. Check whether it still asks "
                        "for disclosure or citation.", evidence)
    return _finding("AI_POLICY", "watch",
                    "AI policy is mentioned but unclear",
                    "The syllabus talks about AI without a clear yes or no. "
                    "Ask the instructor what counts as allowed use.", evidence)


def rule_grading(parsed):
    g = parsed.get("grading", {})
    items = g.get("items", [])
    total = g.get("total", 0)
    if not items:
        return _finding("GRADING", "flag",
                        "No grading breakdown found",
                        "SyllabusAI could not find how your grade is calculated. "
                        "You would be enrolling without knowing what counts — "
                        "check the syllabus or ask the instructor.")
    if total != 100:
        return _finding("GRADING", "flag",
                        f"Grading adds up to {total}%, not 100%",
                        "The percentages listed do not add up to a full grade, so "
                        "part of the breakdown may be missing or unstated. Confirm "
                        "the missing piece before you commit.",
                        "; ".join(f"{i['label']} {i['percent']}%" for i in items))
    biggest = max(items, key=lambda i: i["percent"])
    if biggest["percent"] >= 40:
        return _finding("GRADING", "flag",
                        f"{biggest['percent']}% of your grade rides on one item: {biggest['label']}",
                        "Most of your grade depends on a single piece of work. "
                        "That is high stakes if it goes badly — make sure you are "
                        "comfortable with that weight.",
                        "; ".join(f"{i['label']} {i['percent']}%" for i in items))
    return _finding("GRADING", "info",
                    "Grading breakdown is complete",
                    f"Adds up to 100%. Biggest single item is {biggest['label']} "
                    f"at {biggest['percent']}%.",
                    "; ".join(f"{i['label']} {i['percent']}%" for i in items))


def rule_slip_days(parsed):
    slip = parsed.get("slip_days", {})
    late = parsed.get("late_policy", {})
    if slip.get("found") and slip.get("count", -1) >= 0:
        n = slip["count"]
        return _finding("SLIP_DAYS", "info",
                        f"You get {n} slip day{'s' if n != 1 else ''} this semester",
                        "Slip days extend a deadline with no penalty. Check the "
                        "rules for how many you can use on one assignment.",
                        slip.get("text", "")[:300])
    if late.get("found"):
        return _finding("SLIP_DAYS", "watch",
                        "No slip-day policy stated",
                        "The syllabus has a late policy but no slip days, so late "
                        "work is penalized from day one. Plan your deadlines "
                        "carefully.", late.get("text", "")[:300])
    return _finding("SLIP_DAYS", "watch",
                    "No slip-day or late policy found",
                    "Nothing in the syllabus says what happens if work is late. "
                    "Ask the instructor — do not assume there is a grace period.")


def rule_late_policy(parsed):
    late = parsed.get("late_policy", {})
    if not late.get("found"):
        return _finding("LATE_POLICY", "watch",
                        "No late policy found",
                        "The syllabus does not say what happens to late work. "
                        "Ask before you need it.", "")
    text = late.get("text", "")
    low = text.lower()
    evidence = text[:300]
    m = re.search(r"(\d+)\s*%\s*per day", low)
    if "not accepted" in low or "no credit" in low or "zero" in low:
        return _finding("LATE_POLICY", "flag",
                        "Late work is not accepted (or earns zero)",
                        "Miss a deadline and the work may count for nothing. "
                        "This is the strictest kind of late policy.",
                        evidence)
    if m:
        return _finding("LATE_POLICY", "watch",
                        f"Late work loses {m.group(1)}% per day",
                        "Late submissions cost you every day they are late. "
                        "Use slip days first if you have them.", evidence)
    return _finding("LATE_POLICY", "info",
                    "Late policy found",
                    "The syllabus states what happens to late work — read the "
                    "exact wording before you rely on it.", evidence)


def rule_deadlines(parsed):
    deadlines = parsed.get("deadlines", [])
    if not deadlines:
        return _finding("DEADLINES", "flag",
                        "No dated deadlines found",
                        "SyllabusAI could not find any dated deadlines or exam "
                        "dates. The course may still have them — they might be "
                        "listed on Canvas instead of in the syllabus.")
    dated = [d for d in deadlines if d.get("date")]
    # Cluster detection: 3+ deadlines within any 7-day window.
    cluster = None
    if len(dated) >= 3:
        try:
            days = sorted(date.fromisoformat(d["date"]) for d in dated)
            for i in range(len(days)):
                window = [d for d in days if 0 <= (d - days[i]).days <= 7]
                if len(window) >= 3:
                    cluster = (days[i], len(window))
                    break
        except ValueError:
            cluster = None
    kinds = {}
    for d in deadlines:
        kinds[d.get("kind", "other")] = kinds.get(d.get("kind", "other"), 0) + 1
    summary = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(kinds.items()))
    if cluster:
        return _finding("DEADLINES", "flag",
                        f"One week is packed: {cluster[1]} deadlines around {cluster[0].isoformat()}",
                        "Several big items land in the same week. Look at that "
                        "week against your other courses before you commit.",
                        summary)
    exams = [d for d in deadlines if d.get("kind") in ("exam", "midterm", "final_exam")]
    if exams:
        return _finding("DEADLINES", "info",
                        f"{len(deadlines)} key dates found, including {len(exams)} exam(s)",
                        "Deadlines are spread out. Check the exam dates against "
                        "your other courses.", summary)
    return _finding("DEADLINES", "info",
                    f"{len(deadlines)} key dates found",
                    "The syllabus lists dated deadlines. Add them to your "
                    "calendar early.", summary)


def rule_materials(parsed):
    mats = parsed.get("materials", [])
    if not mats:
        return _finding("MATERIALS", "info",
                        "No required materials listed",
                        "The syllabus does not list a textbook or purchases. "
                        "Materials may be posted on Canvas instead.")
    text = " ".join(mats).lower()
    if "$" in text or "purchase" in text or "buy" in text:
        return _finding("MATERIALS", "watch",
                        "Some materials cost money",
                        "Budget for required purchases — the syllabus mentions "
                        "buying a textbook or other materials.",
                        "; ".join(mats)[:300])
    return _finding("MATERIALS", "info",
                    f"{len(mats)} required item(s) listed",
                    "Materials are listed in the syllabus — check whether you "
                    "already own any of them.", "; ".join(mats)[:300])


RULES = [rule_ai_policy, rule_grading, rule_slip_days, rule_late_policy,
         rule_deadlines, rule_materials]


def run_rules(parsed):
    """Run every named rule over the parsed syllabus."""
    return [fn(parsed) for fn in RULES]


def verdict(findings):
    """Compose the 'what this means for you' verdict from the findings."""
    flags = [f for f in findings if f["severity"] == "flag"]
    watches = [f for f in findings if f["severity"] == "watch"]
    if flags:
        tone = "reconsider"
        headline = "Worth a careful look before you stay in this class"
        summary = (f"There {'is' if len(flags) == 1 else 'are'} {len(flags)} "
                   f"thing{'s' if len(flags) != 1 else ''} that could catch you "
                   f"out, plus {len(watches)} smaller watch-out{'s' if len(watches) != 1 else ''}.")
    elif watches:
        tone = "watch"
        headline = "Mostly manageable — but know the rules before week one"
        summary = (f"No red flags, but {len(watches)} thing{'s' if len(watches) != 1 else ''} "
                   f"to be aware of. Read those sections in full.")
    else:
        tone = "clear"
        headline = "Looks straightforward — nothing hidden in the fine print"
        summary = "SyllabusAI found nothing alarming. Still read the full syllabus once."
    bullets = []
    for f in sorted(findings, key=lambda x: SEVERITY_ORDER[x["severity"]]):
        if f["severity"] in ("flag", "watch"):
            bullets.append(f["takeaway"])
    return {"tone": tone, "headline": headline, "summary": summary,
            "bullets": bullets[:4]}
