# SyllabusAI

**Know the class before you commit.** SyllabusAI reads a course syllabus and
pulls out the parts students actually miss — the AI policy, how the grade is
calculated, slip days and late rules, and the dates that decide the semester —
so you can make an informed keep-or-drop decision.

Built for Cornell students. Paste syllabus text, upload a syllabus file
(PDF / text / Markdown), or optionally fetch a syllabus straight from Canvas.

## What it does

- **AI policy** — quoted from the syllabus, classified (allowed / allowed
  with rules / not allowed / not stated), with a plain-language takeaway.
- **Grading breakdown** — every graded item with its percentage, shown as a
  stacked bar; flags it when the numbers do not add up to 100% or when one
  item carries 40%+ of the grade.
- **Slip days & late policy** — how many slip days you get and what late work
  costs you.
- **Key dates** — deadlines, midterms, finals, and project dates, sorted and
  labeled, with a flag when several land in the same week.
- **Required materials** — textbook and other required items.
- **"What this means for you" verdict** — red flags, watch-outs, and a
  straight summary of whether the class is worth a careful second look.

## Architecture

The design mirrors the spec — a **C++ parser** and a **rules engine** — with
one pragmatic substitution documented below:

| Layer | Implementation |
|---|---|
| Parser | C++ (`backend/parser_cpp/syllabus_parser.cpp`) — segments sections and extracts course info, AI policy, grading, slip days, deadlines, materials as JSON |
| Rules engine | Python (`backend/app/rules.py`) — named rules `AI_POLICY`, `GRADING`, `SLIP_DAYS`, `LATE_POLICY`, `DEADLINES`, `MATERIALS`, plus a `VERDICT` composer. Same rule names, input shape, and finding shape as the intended OCaml engine |
| Service | FastAPI (`backend/app/main.py`) — `/api/analyze`, `/api/analyze-file`, `/api/canvas`, `/api/sample`, `/api/health` |
| Canvas | `backend/app/canvas_client.py` — fetches a course syllabus via the Canvas API with a token the student pastes for one fetch. The token is never stored or logged |
| Frontend | React + Vite + TypeScript (`frontend/`) — Canvas-inspired clarity (course-card header, clear sections) with SyllabusAI's own look |

**Why the rules engine is Python, not OCaml:** OCaml is not installed in the
build environment and cannot be installed there (package archives blocked).
The Python rules engine keeps the exact rule structure so an OCaml port is a
direct translation — that port is the next step, not a redesign. The C++
parser is real and wired in: the service shells out to the compiled binary
and falls back to a pure-Python extractor only if the binary is missing.

## Run locally

```bash
# Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
g++ -std=c++17 -O2 -o parser_cpp/syllabus_parser parser_cpp/syllabus_parser.cpp
SYLLABUS_PARSER_BIN=$PWD/parser_cpp/syllabus_parser \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# Frontend (second terminal)
cd frontend
npm install && npm run dev   # http://localhost:5173, /api proxied to :8000
```

Or build the whole thing as one service (what Render runs):

```bash
cd frontend && npm install && npm run build
cp -r dist ../backend/frontend_dist
cd ../backend && .venv/bin/uvicorn app.main:app --port 8000
# open http://localhost:8000
```

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `PORT` | No (Render sets it) | Port the service listens on |
| `SYLLABUS_PARSER_BIN` | No | Path to the compiled C++ parser; set in the Dockerfile. Without it the service uses the Python fallback parser |

No API keys, no database, no secrets. Nothing the user pastes or uploads is
stored — analysis is stateless.

## Sample syllabus

`backend/app/sample_syllabus.txt` is a **fictional** Cornell-style syllabus
(INFO 3100, invented instructor and policies) labeled as a sample. It exists
so the demo works without a real syllabus. No real course's syllabus is
copied anywhere in this project.

## Deploy

Render Blueprint: `render.yaml` at the project root defines a single free
Docker web service (`syllabus-ai`) that builds the frontend, compiles the
C++ parser, and serves the API + site from one URL. Health check:
`/api/health`.

## Verify

```bash
cd backend
.venv/bin/python tests/verify.py   # boots against a running server on :8123
```

The suite covers: sample-syllabus extraction end to end, PDF upload, the
Canvas fetch path against a stub server, and an edge-case syllabus (missing
AI policy, grading that does not add up, no slip days, clustered deadlines).
