"""Xiaohongshu note peek (owner 2026-07-23).

XHS /explore/ URLs used to go wholesale down the yt-dlp video path, but many
notes are image/text posts (图文) with no video — yt-dlp fails deterministically
("No video formats found") and the item wedged as "deferred" forever, while the
note body sat in the page HTML the whole time (`window.__INITIAL_STATE__`).

So `ingest_one` peeks here first: one plain policy-client GET (honest UA — XHS
serves the full embedded state to it, verified 2026-07-23), parse the note, and
an image note becomes webpage text on the spot. A video note, or ANY fetch/parse
miss, returns None and the yt-dlp path runs unchanged (best-effort, FR-2).
`image_urls` are carried for the upcoming selective image-reading (VL) stage —
for 图文 notes most of the information lives in the images.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.clients.base import VisionClient

_STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*\{")
# the blob is JS, not strict JSON: bare `undefined` appears as a value
_UNDEFINED_RE = re.compile(r"([:,\[])\s*undefined")


@dataclass(frozen=True)
class XhsNote:
    note_id: str
    title: str
    desc: str
    is_video: bool
    image_urls: tuple[str, ...]


def _state_blob(html: str) -> str | None:
    """The `window.__INITIAL_STATE__` object literal, by brace matching that is
    string-aware (desc text may contain braces)."""
    m = _STATE_RE.search(html)
    if m is None:
        return None
    start = m.end() - 1
    depth, in_str, esc = 0, False, False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return html[start : i + 1]
    return None


def parse_note_html(html: str) -> XhsNote | None:
    """Extract the note from an XHS note page; None on any miss (login wall,
    layout change, truncated page) — the caller falls back to the yt-dlp path."""
    blob = _state_blob(html)
    if blob is None:
        return None
    try:
        state = json.loads(_UNDEFINED_RE.sub(r"\1null", blob))
    except ValueError:
        return None
    detail_map = state.get("note", {}).get("noteDetailMap")
    if not isinstance(detail_map, dict):
        return None
    for note_id, entry in detail_map.items():
        note: Any = entry.get("note") if isinstance(entry, dict) else None
        if not isinstance(note, dict) or not note:
            continue
        images = tuple(
            url
            for img in note.get("imageList") or []
            if isinstance(img, dict) and (url := img.get("urlDefault") or img.get("url"))
        )
        return XhsNote(
            note_id=str(note_id),
            title=str(note.get("title") or "").strip(),
            desc=str(note.get("desc") or "").strip(),
            is_video=note.get("type") == "video" or "video" in note,
            image_urls=images,
        )
    return None


def fetch_note(url: str, *, client: httpx.Client) -> XhsNote | None:
    """Best-effort page peek: any network/status/parse problem → None, and the
    caller's yt-dlp path still produces its own typed failure."""
    try:
        resp = client.get(url)
        if resp.status_code != 200:
            return None
        return parse_note_html(resp.text)
    except Exception:
        return None


# a note can carry up to ~18 images; OCR is sub-second each, so read them all
# short of pathological cases
_MAX_OCR_IMAGES = 18


def read_note_images(
    image_urls: tuple[str, ...], *, client: httpx.Client, vision: VisionClient | None
) -> str:
    """OCR the note's images into one labeled text block ("" when there is no
    reader or nothing readable). Per-image failures are skipped silently —
    image text is enrichment for the note body, never a reason to fail it."""
    if vision is None or not image_urls:
        return ""
    sections: list[str] = []
    for i, image_url in enumerate(image_urls[:_MAX_OCR_IMAGES], 1):
        try:
            resp = client.get(image_url)
            if resp.status_code != 200:
                continue
            text = vision.read_image(resp.content).strip()
        except Exception:
            continue
        if text:
            sections.append(f"【图{i}】\n{text}")
    if not sections:
        return ""
    # the label keeps provenance honest inside the stored excerpt itself
    return "图片文字(本地识别):\n\n" + "\n\n".join(sections)
