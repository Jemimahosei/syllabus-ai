"""End-to-end verification for SyllabusAI (run while the dev server is up).

Checks:
 1. POST /api/analyze with the sample syllabus -> AI policy, grading 100%,
    slip days 3, 8 deadlines, materials, verdict.
 2. POST /api/analyze-file with a PDF generated from the sample text.
 3. POST /api/canvas against a local stub Canvas server (no real token).
 4. Edge-case syllabus: no AI policy, grading sums to 60%, no slip days,
    clustered deadlines -> expect the right flags.
"""
import io
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE = "http://127.0.0.1:8123"
SAMPLE = open("/home/hatch/workspace/projects/syllabus-ai/backend/app/sample_syllabus.txt").read()

passed, failed = [], []


def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))


def post_json(path, obj):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"_raw": raw[:300].decode("utf-8", "replace")}


# --- 1. sample text analysis ---
status, d = post_json("/api/analyze", {"text": SAMPLE})
check("analyze status 200", status == 200, f"got {status}")
check("engine is cpp", d.get("parser_engine") == "cpp", d.get("parser_engine"))
check("course code INFO 3100", d["course"]["code"] == "INFO 3100", d["course"])
check("course term Fall 2026", d["course"]["term"] == "Fall 2026", d["course"])
ai = d["ai_policy"]
check("AI policy found", ai["found"] is True)
check("AI stance allowed_with_rules", ai["stance"] == "allowed_with_rules", ai["stance"])
check("AI quotes present", len(ai["quotes"]) >= 1)
g = d["grading"]
check("grading 5 items", len(g["items"]) == 5, str(g["items"]))
check("grading total 100", g["total"] == 100, str(g["total"]))
check("grading has final project 30", any(i["label"] == "Final project" and i["percent"] == 30 for i in g["items"]))
check("slip days = 3", d["slip_days"]["found"] and d["slip_days"]["count"] == 3, str(d["slip_days"]))
check("late policy found", d["late_policy"]["found"] is True)
check("8 deadlines", len(d["deadlines"]) == 8, str(len(d["deadlines"])))
check("midterm date normalized", any(x["label"] == "Midterm exam" and x["date"] == "2026-10-22" for x in d["deadlines"]))
check("materials = 3", len(d["materials"]) == 3, str(d["materials"]))
check("verdict present", d["verdict"]["headline"] and d["verdict"]["summary"])
rules = {f["rule"] for f in d["findings"]}
check("all 6 rules ran", rules == {"AI_POLICY", "GRADING", "SLIP_DAYS", "LATE_POLICY", "DEADLINES", "MATERIALS"}, str(rules))
check("sample verdict tone is watch (AI rules + late policy)", d["verdict"]["tone"] == "watch", d["verdict"]["tone"])

# --- 2. PDF upload ---
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas
buf = io.BytesIO()
c = rl_canvas.Canvas(buf, pagesize=letter)
y = 750
for line in SAMPLE.splitlines():
    c.drawString(40, y, line[:110])
    y -= 13
    if y < 40:
        c.showPage()
        y = 750
c.save()
pdf_bytes = buf.getvalue()
boundary = "----verifyboundary"
body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"sample.pdf\"\r\nContent-Type: application/pdf\r\n\r\n").encode() \
    + pdf_bytes + f"\r\n--{boundary}--\r\n".encode()
req = urllib.request.Request(BASE + "/api/analyze-file", data=body,
                             headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                             method="POST")
try:
    with urllib.request.urlopen(req) as r:
        d2 = json.load(r)
        st = r.status
except urllib.error.HTTPError as e:
    d2, st = json.load(e), e.code
check("pdf upload status 200", st == 200, f"got {st}: {str(d2)[:200]}")
if st == 200:
    check("pdf: grading total 100", d2["grading"]["total"] == 100, str(d2["grading"]))
    check("pdf: slip days 3", d2["slip_days"]["count"] == 3, str(d2["slip_days"]))
    check("pdf: AI stance", d2["ai_policy"]["stance"] == "allowed_with_rules", d2["ai_policy"]["stance"])

# --- 3. Canvas stub ---
STUB_BODY = ("<h1>CS 1110: Introduction to Computing</h1>"
             "<h2>Grading</h2><p>Assignments: 50%<br>Midterm: 20%<br>Final: 30%</p>"
             "<h2>Artificial Intelligence Policy</h2><p>Use of ChatGPT is prohibited "
             "in this course. Do not use AI tools on any assignment.</p>"
             "<p>Midterm exam: October 14, 2026. Final project due December 9, 2026.</p>")


class Stub(BaseHTTPRequestHandler):
    def do_GET(self):
        assert "Authorization" in self.headers, "missing auth header"
        assert self.headers["Authorization"].startswith("Bearer "), "bad auth scheme"
        assert self.path.startswith("/api/v1/courses/999"), f"unexpected path {self.path}"
        payload = json.dumps({"id": 999, "name": "CS 1110",
                              "syllabus_body": STUB_BODY}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 8765), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
status, d3 = post_json("/api/canvas", {"token": "fake-token-for-test",
                                       "course": "https://canvas.cornell.edu/courses/999",
                                       "base_url": "http://127.0.0.1:8765"})
check("canvas stub status 200", status == 200, f"got {status}: {str(d3)[:200]}")
if status == 200:
    check("canvas: AI stance prohibited", d3["ai_policy"]["stance"] == "prohibited", d3["ai_policy"]["stance"])
    check("canvas: grading total 100", d3["grading"]["total"] == 100, str(d3["grading"]))
    check("canvas: course name from Canvas", d3["course"].get("name_from_canvas") == "CS 1110", str(d3["course"]))
    check("canvas: token never echoed", "fake-token-for-test" not in json.dumps(d3))
srv.shutdown()

# bad token against stub that 401s
status, d4 = post_json("/api/canvas", {"token": "x", "course": "999",
                                       "base_url": "http://127.0.0.1:9"})
check("canvas unreachable -> clean 400", status == 400, f"got {status}")

# --- 4. edge-case syllabus ---
EDGE = """CS 9999: Topics in Testing
Spring 2027
Instructor: Dr. Lee

Grading
- Assignments: 30%
- Final exam: 30%

Late Work
Late work is not accepted. No credit for anything turned in after the deadline.

Schedule
- Assignment 1 due: March 3, 2027.
- Assignment 2 due: March 5, 2027.
- Midterm exam: March 6, 2027.
"""
status, d5 = post_json("/api/analyze", {"text": EDGE})
check("edge status 200", status == 200, f"got {status}")
if status == 200:
    check("edge: AI not found", d5["ai_policy"]["found"] is False)
    check("edge: grading total 60", d5["grading"]["total"] == 60, str(d5["grading"]))
    check("edge: no slip days", d5["slip_days"]["found"] is False)
    check("edge: cluster flag raised",
          any(f["rule"] == "DEADLINES" and f["severity"] == "flag" for f in d5["findings"]),
          str(d5["findings"]))
    check("edge: late-not-accepted flag raised",
          any(f["rule"] == "LATE_POLICY" and f["severity"] == "flag" for f in d5["findings"]))
    check("edge: verdict tone reconsider", d5["verdict"]["tone"] == "reconsider", d5["verdict"]["tone"])

print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED:", failed)
    raise SystemExit(1)
