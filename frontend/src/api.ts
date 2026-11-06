export interface Course {
  code: string
  title: string
  instructor: string
  term: string
  name_from_canvas?: string
}

export interface AiPolicy {
  found: boolean
  stance: string
  text: string
  quotes: string[]
}

export interface GradingItem {
  label: string
  percent: number
}

export interface Deadline {
  label: string
  date_raw: string
  date: string
  kind: string
  context: string
}

export interface Finding {
  rule: string
  severity: 'flag' | 'watch' | 'info'
  title: string
  takeaway: string
  evidence: string
}

export interface Analysis {
  source: string
  parser_engine: string
  course: Course
  ai_policy: AiPolicy
  grading: { items: GradingItem[]; total: number }
  slip_days: { found: boolean; count: number; text: string }
  late_policy: { found: boolean; text: string }
  deadlines: Deadline[]
  materials: string[]
  findings: Finding[]
  verdict: { tone: string; headline: string; summary: string; bullets: string[] }
}

async function handle(res: Response): Promise<Analysis> {
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`)
  }
  return data as Analysis
}

export async function analyzeText(text: string): Promise<Analysis> {
  const res = await fetch('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  return handle(res)
}

export async function analyzeFile(file: File): Promise<Analysis> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/analyze-file', { method: 'POST', body: form })
  return handle(res)
}

export async function analyzeCanvas(
  token: string,
  course: string,
): Promise<Analysis> {
  const res = await fetch('/api/canvas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, course }),
  })
  return handle(res)
}

export async function fetchSample(): Promise<string> {
  const res = await fetch('/api/sample')
  const data = await res.json()
  return data.text as string
}

export const KIND_LABELS: Record<string, string> = {
  homework: 'Homework',
  midterm: 'Midterm',
  final_exam: 'Final exam',
  final_project: 'Final project',
  final: 'Final',
  quiz: 'Quiz',
  proposal: 'Proposal',
  presentation: 'Presentation',
  project: 'Project',
  exam: 'Exam',
  other: 'Date',
}

export const STANCE_LABELS: Record<string, string> = {
  allowed: 'AI allowed',
  allowed_with_rules: 'AI allowed with rules',
  prohibited: 'AI not allowed',
  unclear: 'AI policy unclear',
  not_stated: 'No AI policy stated',
}
