"""Canvas client — optional, session-only.

Fetches a course syllabus from the Canvas LMS API using a token the student
pastes in for one fetch. The token is used ONLY for this single request:
it is never stored, never logged, and never sent anywhere else.

Canvas API: GET /api/v1/courses/:id?include[]=syllabus_body
with header  Authorization: Bearer <token>
Response field `syllabus_body` is HTML; it is converted to plain text.

The student's Canvas API token is NOT available to SyllabusAI by default —
the paste/upload flow is the primary path and Canvas is a clearly-marked
optional path. Do NOT use any token from memory or files here: the Canvas
calendar feed token used for deadline sync is for calendar sync only,
not API access.
"""

from __future__ import annotations

import html
import re

import httpx

DEFAULT_BASE_URL = "https://canvas.cornell.edu"


class CanvasError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def extract_course_id(course: str) -> str:
    """Accept a bare course id ('12345') or a Canvas course URL."""
    course = course.strip()
    m = re.search(r"/courses/(\d+)", course)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d+", course):
        return course
    raise CanvasError("Could not read a course id. Paste a Canvas course URL "
                      "or a numeric course id (for example 12345).")


def html_to_text(raw_html: str) -> str:
    """Convert Canvas syllabus HTML to readable plain text."""
    text = re.sub(r"(?i)<br\s*/?>", "\n", raw_html)
    text = re.sub(r"(?i)</(p|div|h[1-6]|li|tr|ul|ol)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


async def fetch_syllabus(token: str, course: str,
                         base_url: str = DEFAULT_BASE_URL) -> dict:
    """Fetch one course's syllabus. Returns {'course_name', 'text'}.

    Raises CanvasError with a plain-language message on failure.
    The token is held only in this call's local scope.
    """
    token = (token or "").strip()
    if not token:
        raise CanvasError("Paste your Canvas API token first. It is used "
                          "only for this one fetch and is never stored.")
    course_id = extract_course_id(course)
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/api/v1/courses/{course_id}"
    try:
        # trust_env=False: never route the request (or its Bearer token)
        # through a proxy from the environment.
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            resp = await client.get(
                url,
                params={"include[]": "syllabus_body"},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.RequestError as exc:
        raise CanvasError("Could not reach Canvas. Check your connection and "
                          "try again.") from exc
    if resp.status_code == 401:
        raise CanvasError("Canvas rejected the token. Check that you pasted "
                          "a current Canvas API token.", status=401)
    if resp.status_code == 404:
        raise CanvasError("That course was not found on Canvas. Check the "
                          "course id or URL.", status=404)
    if resp.status_code != 200:
        raise CanvasError(f"Canvas returned an error ({resp.status_code}). "
                          "Try again, or paste the syllabus text instead.",
                          status=resp.status_code)
    data = resp.json()
    body = data.get("syllabus_body") or ""
    if not body.strip():
        raise CanvasError("This course has no syllabus posted on Canvas. "
                          "Paste the syllabus text instead.")
    name = data.get("name") or data.get("course_code") or ""
    return {"course_name": name, "text": html_to_text(body)}
