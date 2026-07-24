"""Xiaohongshu note peek (owner 2026-07-23): 图文 notes become webpage text from
the embedded page state instead of wedging on the yt-dlp video path; video notes
and any fetch/parse miss still route to yt-dlp. All offline (NFR-3)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import httpx

from app.ingestion.ingest import ingest_one
from app.ingestion.router import is_xiaohongshu_note
from app.ingestion.xiaohongshu import parse_note_html
from app.schemas.models import SourceRequest

NOTE_URL = "https://www.xiaohongshu.com/explore/6a60e793000000000100c12e?xsec_token=ABC"

_IMAGE_NOTE: dict[str, Any] = {
    "type": "normal",
    "title": "DeepSeek投资人会议语录",
    # braces and quotes exercise the string-aware brace matcher
    "desc": '上个月报道了 DeepSeek 的融资故事。语录 {带括号} 与 "引号" 都要活着。',
    "imageList": [
        {"urlDefault": "http://sns-webpic-qc.xhscdn.com/a.jpg", "url": ""},
        {"url": "http://sns-webpic-qc.xhscdn.com/b.jpg"},
    ],
}

_VIDEO_NOTE: dict[str, Any] = {
    "type": "video",
    "title": "一个视频笔记",
    "desc": "视频简介",
    "video": {"media": {}},
    "imageList": [{"urlDefault": "http://sns-webpic-qc.xhscdn.com/cover.jpg"}],
}


def _note_page(note: dict[str, Any], *, note_id: str = "6a60e793000000000100c12e") -> str:
    state = {
        "global": {"trace": None},  # becomes a bare JS `undefined` below
        "note": {"noteDetailMap": {note_id: {"note": note, "comments": {"list": []}}}},
    }
    blob = json.dumps(state, ensure_ascii=False).replace("null", "undefined")
    return f"<html><body><script>window.__INITIAL_STATE__={blob}</script></body></html>"


class _PageClient:
    """Serves the canned note HTML for the page GET and canned bytes for image
    GETs (or an error) — offline."""

    def __init__(self, html: str | None, status_code: int = 200) -> None:
        self._html = html
        self._status = status_code
        self.calls: list[str] = []

    def get(self, url: str) -> Any:
        self.calls.append(url)
        if self._html is None:
            raise httpx.ConnectError("boom")
        if url.endswith(".jpg"):  # an image download
            return SimpleNamespace(content=f"IMG:{url}".encode(), status_code=200)
        return SimpleNamespace(text=self._html, status_code=self._status)

    def close(self) -> None:
        pass


class _FakeOCR:
    """VisionClient fake: fixed text per image; records what it was fed."""

    def __init__(self, text_by_suffix: dict[str, str]) -> None:
        self._by_suffix = text_by_suffix
        self.seen: list[bytes] = []

    def read_image(self, image: bytes) -> str:
        self.seen.append(image)
        for suffix, text in self._by_suffix.items():
            if image.decode().endswith(suffix):
                return text
        return ""


class _NoOCR:
    def read_image(self, image: bytes) -> str:
        return ""


# --- URL classification -------------------------------------------------------


def test_is_xiaohongshu_note_url_matrix() -> None:
    assert is_xiaohongshu_note(NOTE_URL)
    assert is_xiaohongshu_note("https://www.xiaohongshu.com/discovery/item/abc123")
    assert is_xiaohongshu_note("https://m.xiaohongshu.com/explore/abc123")
    assert is_xiaohongshu_note("http://xhslink.com/o/AbCd")
    assert not is_xiaohongshu_note("https://www.xiaohongshu.com/user/profile/123")
    assert not is_xiaohongshu_note("https://www.youtube.com/watch?v=demo")


# --- page-state parsing --------------------------------------------------------


def test_parse_image_note_extracts_text_and_images() -> None:
    note = parse_note_html(_note_page(_IMAGE_NOTE))
    assert note is not None
    assert note.note_id == "6a60e793000000000100c12e"
    assert note.title == "DeepSeek投资人会议语录"
    assert "{带括号}" in note.desc and '"引号"' in note.desc
    assert note.is_video is False
    # urlDefault preferred; a missing urlDefault falls back to url
    assert note.image_urls == (
        "http://sns-webpic-qc.xhscdn.com/a.jpg",
        "http://sns-webpic-qc.xhscdn.com/b.jpg",
    )


def test_parse_video_note_is_flagged_video() -> None:
    note = parse_note_html(_note_page(_VIDEO_NOTE))
    assert note is not None and note.is_video is True


def test_parse_misses_return_none() -> None:
    assert parse_note_html("<html>no state here</html>") is None
    assert parse_note_html(_note_page(_IMAGE_NOTE)[:200]) is None  # truncated blob
    assert parse_note_html('<script>window.__INITIAL_STATE__={"note":{}}</script>') is None


# --- ingest routing -------------------------------------------------------------


def test_ingest_image_note_becomes_webpage_text_without_ytdlp() -> None:
    client = _PageClient(_note_page(_IMAGE_NOTE))
    extractor_calls: list[str] = []

    def _extractor(url: str) -> dict[str, Any]:
        extractor_calls.append(url)
        raise RuntimeError("yt-dlp path must not run for an image note")

    result = ingest_one(
        SourceRequest(kind="url", url=NOTE_URL),
        http_client=cast(httpx.Client, client),
        caption_extractor=_extractor,
        vision_client=_NoOCR(),
    )
    assert result.status == "ok" and result.source is not None
    assert result.source.type == "webpage"
    assert result.source.extraction_method == "structured_html"
    assert "DeepSeek投资人会议语录" in result.source.raw_text
    assert "融资故事" in result.source.raw_text
    assert extractor_calls == []  # never entered the yt-dlp path


def test_ingest_image_note_appends_local_ocr_text_and_marks_frame_ocr() -> None:
    # owner 2026-07-23 "看图也要做": the 语录 screenshots ARE the content — the
    # on-device OCR reads them into the excerpt, labeled per image
    ocr = _FakeOCR({"a.jpg": "1. 现在做产品不是收益最大化的时候。", "b.jpg": ""})
    client = _PageClient(_note_page(_IMAGE_NOTE))
    result = ingest_one(
        SourceRequest(kind="url", url=NOTE_URL),
        http_client=cast(httpx.Client, client),
        vision_client=ocr,
    )
    assert result.status == "ok" and result.source is not None
    assert result.source.extraction_method == "frame_ocr"
    assert "融资故事" in result.source.raw_text  # desc still present
    assert "图片文字(本地识别):" in result.source.raw_text
    assert "【图1】\n1. 现在做产品不是收益最大化的时候。" in result.source.raw_text
    assert "【图2】" not in result.source.raw_text  # blank OCR → no empty section
    assert len(ocr.seen) == 2  # both images were fed to the reader


def test_ingest_image_note_ocr_failure_degrades_to_the_note_text() -> None:
    class _BoomOCR:
        def read_image(self, image: bytes) -> str:
            raise RuntimeError("vision exploded")

    client = _PageClient(_note_page(_IMAGE_NOTE))
    result = ingest_one(
        SourceRequest(kind="url", url=NOTE_URL),
        http_client=cast(httpx.Client, client),
        vision_client=_BoomOCR(),
    )
    assert result.status == "ok" and result.source is not None
    assert result.source.extraction_method == "structured_html"
    assert "融资故事" in result.source.raw_text


def test_ingest_imageonly_note_is_rescued_by_ocr() -> None:
    bare = dict(_IMAGE_NOTE, title="", desc="")
    ocr = _FakeOCR({"a.jpg": "只存在于截图里的正文", "b.jpg": ""})
    client = _PageClient(_note_page(bare))
    result = ingest_one(
        SourceRequest(kind="url", url=NOTE_URL),
        http_client=cast(httpx.Client, client),
        vision_client=ocr,
    )
    assert result.status == "ok" and result.source is not None
    assert result.source.extraction_method == "frame_ocr"
    assert "只存在于截图里的正文" in result.source.raw_text


def test_ingest_image_note_without_text_is_a_typed_parse_empty() -> None:
    bare = dict(_IMAGE_NOTE, title="", desc="")
    client = _PageClient(_note_page(bare))
    result = ingest_one(
        SourceRequest(kind="url", url=NOTE_URL),
        http_client=cast(httpx.Client, client),
        vision_client=_NoOCR(),
    )
    assert result.status == "failed" and result.failure is not None
    assert result.failure.kind == "parse_empty"
    assert "image" in result.failure.reason


def test_ingest_video_note_falls_through_to_the_ytdlp_path() -> None:
    def _no_captions(_url: str) -> dict[str, Any]:
        raise RuntimeError("no caption track")

    client = _PageClient(_note_page(_VIDEO_NOTE))
    result = ingest_one(
        SourceRequest(kind="url", url=NOTE_URL),
        http_client=cast(httpx.Client, client),
        caption_extractor=_no_captions,
        allow_transcription=False,
    )
    # transcription_deferred proves the video route ran (M14.5 first-check defer)
    assert result.status == "failed" and result.failure is not None
    assert result.failure.kind == "transcription_deferred"


def test_ingest_page_peek_failure_falls_through_to_the_ytdlp_path() -> None:
    def _no_captions(_url: str) -> dict[str, Any]:
        raise RuntimeError("no caption track")

    client = _PageClient(None)  # the peek GET raises; best-effort → old path
    result = ingest_one(
        SourceRequest(kind="url", url=NOTE_URL),
        http_client=cast(httpx.Client, client),
        caption_extractor=_no_captions,
        allow_transcription=False,
    )
    assert result.status == "failed" and result.failure is not None
    assert result.failure.kind == "transcription_deferred"
