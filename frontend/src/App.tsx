import { useMemo, useRef, useState } from 'react'
import {
  analyzeCanvas,
  analyzeFile,
  analyzeText,
  fetchSample,
  KIND_LABELS,
  STANCE_LABELS,
  type Analysis,
} from './api'

type Tab = 'paste' | 'upload' | 'canvas'

const GRADE_COLORS = ['#1b2a41', '#b31b1b', '#1f6f8b', '#9a6b0f', '#4c7a45', '#6b4fa1']

function formatDate(d: Deadline): string {
  if (d.date) {
    const [y, m, day] = d.date.split('-').map(Number)
    return new Date(y, m - 1, day).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  }
  return d.date_raw
}

type Deadline = Analysis['deadlines'][number]

export default function App() {
  const [tab, setTab] = useState<Tab>('paste')
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [token, setToken] = useState('')
  const [course, setCourse] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingSample, setLoadingSample] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Analysis | null>(null)
  const resultsRef = useRef<HTMLDivElement>(null)

  const sortedDeadlines = useMemo(() => {
    if (!result) return []
    return [...result.deadlines].sort((a, b) => {
      if (a.date && b.date) return a.date.localeCompare(b.date)
      if (a.date) return -1
      if (b.date) return 1
      return 0
    })
  }, [result])

  async function run(fn: () => Promise<Analysis>) {
    setLoading(true)
    setError(null)
    try {
      const data = await fn()
      setResult(data)
      setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  async function onAnalyzePaste() {
    if (!text.trim()) {
      setError('Paste the syllabus text first.')
      return
    }
    await run(() => analyzeText(text))
  }

  async function onAnalyzeFile() {
    if (!file) {
      setError('Choose a syllabus file first (.pdf, .txt, or .md).')
      return
    }
    await run(() => analyzeFile(file))
  }

  async function onAnalyzeCanvas() {
    if (!token.trim() || !course.trim()) {
      setError('Paste your Canvas API token and a course id or URL.')
      return
    }
    await run(() => analyzeCanvas(token, course))
  }

  async function onTrySample() {
    setLoadingSample(true)
    setError(null)
    try {
      const sample = await fetchSample()
      setText(sample)
      setTab('paste')
      await run(() => analyzeText(sample))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the sample.')
    } finally {
      setLoadingSample(false)
    }
  }

  const verdict = result?.verdict
  const stance = result?.ai_policy.stance ?? 'not_stated'

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <span className="brand">
            Syllabus<em>AI</em>
          </span>
          <span className="topbar-tag">for Cornell</span>
          <span className="topbar-sub">Know the class before you commit</span>
        </div>
      </header>

      <main className="page">
        <section className="hero">
          <h1>Read the syllabus. See what actually matters.</h1>
          <p>
            Paste a syllabus and SyllabusAI pulls out the parts students miss —
            the AI policy, how your grade is calculated, slip days, and the dates
            that decide your semester — so you can make an informed keep-or-drop
            decision.
          </p>
        </section>

        <section className="card">
          <h2>Check a syllabus</h2>
          <p className="hint">
            Your syllabus never leaves this page except to be analyzed. Nothing
            you paste or upload is stored.
          </p>

          <div className="tabs">
            <button className={tab === 'paste' ? 'tab active' : 'tab'} onClick={() => setTab('paste')}>
              Paste text
            </button>
            <button className={tab === 'upload' ? 'tab active' : 'tab'} onClick={() => setTab('upload')}>
              Upload file
            </button>
            <button className={tab === 'canvas' ? 'tab active' : 'tab'} onClick={() => setTab('canvas')}>
              Canvas (optional)
            </button>
          </div>

          {tab === 'paste' && (
            <>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Paste the full syllabus text here…"
                aria-label="Syllabus text"
              />
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" onClick={onAnalyzePaste} disabled={loading}>
                  {loading && <span className="spinner" />}Analyze syllabus
                </button>
                <button className="btn btn-ghost" onClick={onTrySample} disabled={loadingSample || loading}>
                  Try the sample syllabus
                </button>
              </div>
            </>
          )}

          {tab === 'upload' && (
            <>
              <div className="dropzone">
                <p style={{ margin: '0 0 10px' }}>
                  Upload a syllabus as a PDF, text, or Markdown file.
                </p>
                <input
                  type="file"
                  accept=".pdf,.txt,.md,.markdown"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
                {file && <p style={{ margin: '10px 0 0' }}>Selected: {file.name}</p>}
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" onClick={onAnalyzeFile} disabled={loading}>
                  {loading && <span className="spinner" />}Analyze file
                </button>
              </div>
            </>
          )}

          {tab === 'canvas' && (
            <>
              <p className="hint">
                Optional. Paste a Canvas API token and a course to fetch the
                syllabus straight from Canvas. The token is used for this one
                fetch only and is never stored. You can create a token in
                Canvas under Account → Settings → Approved Integrations.
              </p>
              <div className="field">
                <label htmlFor="canvas-token">Canvas API token</label>
                <input
                  id="canvas-token"
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="Paste your Canvas API token"
                  autoComplete="off"
                />
              </div>
              <div className="field">
                <label htmlFor="canvas-course">Course</label>
                <input
                  id="canvas-course"
                  type="text"
                  value={course}
                  onChange={(e) => setCourse(e.target.value)}
                  placeholder="Course id (e.g. 12345) or Canvas course URL"
                />
              </div>
              <div className="row">
                <button className="btn" onClick={onAnalyzeCanvas} disabled={loading}>
                  {loading && <span className="spinner" />}Fetch from Canvas
                </button>
              </div>
            </>
          )}
        </section>

        {error && <div className="error">{error}</div>}

        {result && (
          <div ref={resultsRef}>
            <div className="course-card">
              <div className="code">
                {result.course.code || result.course.name_from_canvas || 'Course'}
                {result.course.term ? ` · ${result.course.term}` : ''}
              </div>
              <h2>{result.course.title || 'Untitled course'}</h2>
              <div className="meta">
                {result.course.instructor || 'Instructor not listed'}
              </div>
              <span className="chip">Source: {result.source}</span>
            </div>

            {verdict && (
              <div className={`verdict ${verdict.tone}`}>
                <h2>{verdict.headline}</h2>
                <p>{verdict.summary}</p>
                {verdict.bullets.length > 0 && (
                  <>
                    <strong>What this means for you</strong>
                    <ul>
                      {verdict.bullets.map((b, i) => (
                        <li key={i}>{b}</li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            )}

            <div className="section-title">What SyllabusAI found</div>
            {result.findings.map((f, i) => (
              <div key={i} className={`finding ${f.severity}`}>
                <h3>
                  {f.title}
                  <span className={`badge ${f.severity}`}>
                    {f.severity === 'flag' ? 'Red flag' : f.severity === 'watch' ? 'Watch out' : 'Good to know'}
                  </span>
                </h3>
                <p>{f.takeaway}</p>
                {f.evidence && <p className="evidence">“{f.evidence}”</p>}
              </div>
            ))}

            <div className="section-title">Grading</div>
            <div className="card">
              {result.grading.items.length > 0 ? (
                <>
                  <div className="grade-bar">
                    {result.grading.items.map((item, i) => (
                      <div
                        key={i}
                        className="grade-seg"
                        style={{
                          width: `${item.percent}%`,
                          background: GRADE_COLORS[i % GRADE_COLORS.length],
                        }}
                        title={`${item.label}: ${item.percent}%`}
                      >
                        {item.percent >= 12 ? `${item.percent}%` : ''}
                      </div>
                    ))}
                  </div>
                  <ul className="grade-list">
                    {result.grading.items.map((item, i) => (
                      <li key={i}>
                        <span>{item.label}</span>
                        <span className="pct">{item.percent}%</span>
                      </li>
                    ))}
                  </ul>
                  <p className="muted" style={{ margin: '10px 0 0' }}>
                    Total: {result.grading.total}%
                    {result.grading.total !== 100 &&
                      ' — this does not add up to 100%, so part of the breakdown may be missing.'}
                  </p>
                </>
              ) : (
                <p className="muted">No grading breakdown was found in this syllabus.</p>
              )}
            </div>

            <div className="section-title">AI policy</div>
            <div className="card">
              <h2>
                {STANCE_LABELS[stance] ?? 'AI policy'}
              </h2>
              {result.ai_policy.found ? (
                <>
                  {result.ai_policy.quotes.map((q, i) => (
                    <p key={i} className="quote">
                      “{q}”
                    </p>
                  ))}
                  <details>
                    <summary>Read the full AI policy text</summary>
                    <p>{result.ai_policy.text}</p>
                  </details>
                </>
              ) : (
                <p className="muted">
                  No AI policy was found in this syllabus. That does not mean AI
                  is allowed — ask the instructor.
                </p>
              )}
            </div>

            <div className="section-title">Slip days &amp; late policy</div>
            <div className="card">
              {result.slip_days.found ? (
                <p>
                  <strong>{result.slip_days.count} slip days</strong> for the
                  semester.
                </p>
              ) : (
                <p className="muted">No slip-day policy was found.</p>
              )}
              {result.late_policy.found ? (
                <p style={{ whiteSpace: 'pre-wrap' }}>{result.late_policy.text}</p>
              ) : (
                <p className="muted">No late policy was found in this syllabus.</p>
              )}
            </div>

            <div className="section-title">Key dates</div>
            <div className="card">
              {sortedDeadlines.length > 0 ? (
                <ul className="dates">
                  {sortedDeadlines.map((d, i) => (
                    <li key={i}>
                      <span className="date">{formatDate(d)}</span>
                      <span>
                        <span className="kind">{KIND_LABELS[d.kind] ?? d.kind}</span>
                        <br />
                        {d.label}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No dated deadlines or exam dates were found.</p>
              )}
            </div>

            <div className="section-title">Required materials</div>
            <div className="card">
              {result.materials.length > 0 ? (
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {result.materials.map((m, i) => (
                    <li key={i}>{m}</li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No required materials were listed.</p>
              )}
            </div>

            <p className="muted" style={{ textAlign: 'center' }}>
              SyllabusAI is a reading aid, not a substitute for the syllabus.
              Always read the full document — and when in doubt, ask the
              instructor.
            </p>
          </div>
        )}

        <footer className="footer">
          SyllabusAI · Built for Cornell students · Canvas tokens are never stored
        </footer>
      </main>
    </>
  )
}
