"""M1A.7 — YouTube caption path: track selection, VTT parsing (EN+ZH retained),
and end-to-end fetch via cassette (offline, yt-dlp never imported)."""

from __future__ import annotations

import sys

import pytest

from app.ingestion.html_static import build_client
from app.ingestion.youtube import (
    extract_info,
    fetch_captions,
    parse_vtt,
    select_caption,
    yt_dlp_opts,
)
from tests import fixtures_loader as fx
from tests.http_cassette import replay

# --- VTT parsing ------------------------------------------------------------


def test_parse_en_vtt() -> None:
    segs = parse_vtt(fx.load_text("captions/youtube_en.vtt"))
    assert len(segs) == 2
    assert segs[0].start_ms == 0 and segs[0].end_ms == 3200
    assert "record data-center revenue" in segs[0].text
    assert "<c>" not in segs[1].text  # inline tags stripped
    assert "strong" in segs[1].text


def test_parse_zh_vtt_retains_chinese() -> None:
    segs = parse_vtt(fx.load_text("captions/youtube_zh.vtt"))
    assert len(segs) == 2
    assert any("一" <= ch <= "鿿" for ch in segs[0].text)  # Chinese preserved (NFR-5)


# --- caption track selection ------------------------------------------------


def test_select_prefers_manual_over_auto() -> None:
    info = fx.load_json("captions/ytdlp_info.json")
    choice = select_caption(info)
    assert choice is not None
    assert choice.lang == "en"
    assert choice.is_auto is False  # manual subtitles beat automatic_captions
    assert choice.url == "https://yt.example/cap/en.vtt"


def test_select_falls_back_to_zh_auto_when_only_choice() -> None:
    info = {"subtitles": {}, "automatic_captions": {"zh-Hans": [{"ext": "vtt", "url": "u"}]}}
    choice = select_caption(info)
    assert choice is not None and choice.lang == "zh-Hans" and choice.is_auto is True


def test_select_none_when_no_en_or_zh() -> None:
    info = {"subtitles": {"fr": [{"ext": "vtt", "url": "u"}]}, "automatic_captions": {}}
    assert select_caption(info) is None


# --- extractor injection (lazy yt-dlp) --------------------------------------


def test_yt_dlp_opts_obey_fetch_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    # metadata fetch is a network path → must obey X0.8 red lines
    monkeypatch.setenv("HTTPS_PROXY", "http://evil.proxy:8080")
    monkeypatch.setenv("ALL_PROXY", "http://evil.proxy:8080")
    opts = yt_dlp_opts()
    assert opts["proxy"] == ""  # direct connection; ignores env proxy (§2.2)
    assert opts["cookiefile"] is None
    assert opts["cookiesfrombrowser"] is None
    assert opts["usenetrc"] is False
    assert opts["geo_bypass"] is False
    assert opts["skip_download"] is True
    assert opts["noplaylist"] is True
    assert isinstance(opts["socket_timeout"], (int, float)) and opts["socket_timeout"] > 0


def test_extract_info_uses_injected_extractor() -> None:
    info = extract_info("https://youtu.be/demo", extractor=lambda u: {"id": u})
    assert info == {"id": "https://youtu.be/demo"}
    assert "yt_dlp" not in sys.modules  # real lib never imported (NFR-3)


# --- end-to-end via cassette ------------------------------------------------


def test_fetch_captions_end_to_end() -> None:
    info = fx.load_json("captions/ytdlp_info.json")
    with replay("caption_en.yaml"), build_client() as client:
        result = fetch_captions("https://youtu.be/demo", client=client, extractor=lambda u: info)
    assert result is not None
    assert result.language == "en"
    assert len(result.segments) == 2
    assert "record data-center revenue" in result.text


def test_fetch_captions_none_when_no_track() -> None:
    with build_client() as client:
        result = fetch_captions(
            "https://youtu.be/x",
            client=client,
            extractor=lambda u: {"subtitles": {}, "automatic_captions": {}},
        )
    assert result is None  # → audio fallback (M1A.8)
