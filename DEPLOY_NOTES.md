# SyllabusAI — deploy notes for the parent agent

## What was built

A complete, working SyllabusAI web app in
`/home/hatch/workspace/projects/syllabus-ai/`:

- **Paste / upload / Canvas analysis** — paste syllabus text, upload a
  PDF / .txt / .md file, or optionally fetch a syllabus from Canvas with a
  token pasted for one fetch only (never stored, never logged). Upload/paste
  is the primary path; Canvas is clearly marked optional.
- **C++ parser (real, wired in)** — `backend/parser_cpp/syllabus_parser.cpp`
  segments sections and extracts course info, AI policy + stance, grading
  items + total, slip-day count, late-policy text, dated deadlines (labels,
  normalized dates, kinds), and required materials as JSON. The FastAPI
  service shells out to the compiled binary per request.
- **Rules engine (Python mirror of the OCaml design)** —
  `backend/app/rules.py` with the named rules `AI_POLICY`, `GRADING`,
  `SLIP_DAYS`, `LATE_POLICY`, `DEADLINES`, `MATERIALS` plus a `VERDICT`
  composer ("what this means for you", tones: clear / watch / reconsider).
  Same rule names, input shape, and finding shape as an OCaml port would
  have; the OCaml port itself is a documented next step (OCaml is not
  installed in this VM and cannot be installed — package archives blocked).
  A pure-Python fallback parser (`backend/app/parser.py`) runs only if the
  C++ binary is missing; it produces identical results on the sample.
- **Frontend** — React + Vite + TypeScript, Canvas-inspired clarity (dark
  navy course-card header, clear sections, stacked grading bar, deadline
  timeline) with SyllabusAI's own warm-paper + carnelian look. Tabs for
  Paste / Upload / Canvas, "Try the sample syllabus" button, verdict banner,
  finding cards with evidence quotes, full-policy expandable text.
- **Sample syllabus** — fictional INFO 3100 syllabus, prominently labeled
  as a sample. No real course content anywhere.
- **Single-service deploy** — `backend/Dockerfile` (multi-stage: Node builds
  the frontend, g++ compiles the parser, Python slim runs FastAPI serving
  API + static frontend) and `render.yaml` (one free Docker web service,
  health check `/api/health`).

## Verification (all in this VM, all passing)

- **C++ parser on the sample syllabus**: course INFO 3100 / Fall 2026 /
  instructor extracted; AI policy found, stance `allowed_with_rules`;
  grading 5 items totaling 100%; slip days 3; late policy found;
  8 deadlines with labels, normalized dates, and kinds; 3 materials;
  9 clean sections. Two parser bugs found and fixed during verification
  (bullet lines misread as headings; percentage lines misread as headings).
- **Backend suite `backend/tests/verify.py`: 35/35 PASS** against the
  running server (parser engine `cpp`): sample-text analysis, PDF upload
  (reportlab-generated PDF from the sample), Canvas fetch against a local
  stub server (token header asserted, prohibited-AI syllabus extracted,
  token never echoed in the response), unreachable-Canvas clean 400, and an
  edge-case syllabus (no AI policy, grading totals 60%, no slip days,
  3 deadlines in one week, late work not accepted) producing the expected
  flags and a `reconsider` verdict. One real bug found and fixed by the
  suite: httpx was honoring a broken proxy env var — the Canvas client now
  uses `trust_env=False` so the Bearer token is never routed via a proxy.
- **Python fallback parser**: identical results to the C++ parser on the
  sample (grading 100, AI stance, slip 3, 8 deadlines, 3 materials).
- **Frontend**: `npm install && npm run build` passes (tsc + vite, 152.79 kB
  JS); the built site is served by the backend (index 200, JS asset 200,
  `/api/sample` 200).
- **Single-service smoke test**: backend serves `/api/health`
  (`{"ok": true, "parser_engine": "cpp"}`) and the frontend from one port.

## Deploy steps for the parent

1. Create a new GitHub repo (e.g. `SyllabusAI`) and push this directory.
   Suggested repo layout is the project root as-is (render.yaml at root).
   Do **not** push `backend/.venv`, `frontend/node_modules`,
   `backend/frontend_dist`, or the compiled `parser_cpp/syllabus_parser`
   (see `.gitignore` — all excluded).
2. On Render, create a Blueprint from the repo (or sync the existing
   Blueprint flow used for the other projects). The Blueprint is
   `render.yaml`: service `syllabus-ai`, env docker, plan free,
   `dockerfilePath: backend/Dockerfile`, `dockerContext: .`,
   health check `/api/health`. No environment variables need setting
   (`PORT` is set by Render; `SYLLABUS_PARSER_BIN` is set in the Dockerfile).
3. **Docker build NOT verified in this VM** (Docker is unavailable here) —
   the first Render deploy is the first real Docker build. If it fails,
   the likely spots are the multi-stage `COPY --from` paths or `npm install`
   in the frontend stage; the local `npm run build` and `g++` compile that
   the Dockerfile mirrors both pass here.
4. After deploy, verify live: `GET /api/health` shows
   `parser_engine: "cpp"`; open the site, click "Try the sample syllabus",
   and confirm the verdict + grading bar + 8 key dates render.

## Known limitations / next steps

- **Canvas needs jem's token at runtime.** She pastes it in the UI per
  session; nothing is stored. The full Canvas path has only been verified
  against a stub server, not real Canvas — she should try it with her real
  token once live.
- **OCaml rules engine is a Python mirror**, not an OCaml program. Porting
  `backend/app/rules.py` to OCaml is a direct translation (same rule names
  and finding shape) and is the honest next step if she wants the spec
  stack literally.
- **Free-tier sleep**: Render free services sleep when idle (~50s first
  load), same as the other projects.
- No database, no accounts, no storage of any kind: analysis is stateless.
  The only "state" is the sample syllabus file served by the API.
