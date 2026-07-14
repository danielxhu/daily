# Offline test strategy (X0.3 → NFR-3)

The suite runs with **zero network access and zero API spend**. Every call that
would touch the wire or a paid API in production goes through one of these seams:

| Production call | Test seam | Where |
|---|---|---|
| Network sockets (any) | autouse ban: non-local `connect` raises `NetworkAccessAttempted` | `netban.py` (installed in `conftest.py`) |
| DeepSeek text LLM | `LLMClient` Protocol → `MockLLMClient` (canned JSON, FIFO) | `app/clients/{base,mock}.py` |
| Vision (VL) | `VLClient` Protocol → `MockVLClient` | `app/clients/{base,mock}.py` |
| Speech-to-text (whisper) | `Transcriber` Protocol → `MockTranscriber` (real model never loaded) | `app/clients/{base,mock}.py` |
| Headless render (Playwright) | `RenderClient` Protocol → `MockRenderClient` (no browser launched) | `app/clients/{base,mock}.py` |
| Raw HTTP fetch (static HTML, CASR, feeds) | recorded **vcrpy cassette**, `record_mode="none"` | `http_cassette.py` + `cassettes/` |

## HTTP cassettes (`vcrpy`, SSOT §9.2)

`http_cassette.replay("name.yaml")` serves recorded HTTP via `httpx` and raises on
any un-recorded request — it never records and never hits the network. Cassettes
are recorded deliberately (outside the offline suite, `record_mode="once"` against
the real endpoint), then checked into `cassettes/`. See `test_http_cassette.py`.

## PDF fixtures

`fixtures/text_sample.pdf` is a real, valid **text-layer** PDF carrying known text,
the deterministic input for M1B.3 text extraction (`pypdf`/`pdfplumber`). A
**scanned / image-only** PDF (no text layer) is not shipped as a binary here; per
FR-2 it maps to a typed `unsupported_file` skip — exercised once the failure
taxonomy (M1A.1) and PDF extraction (M1B.3) land.

## Two layers of safety

The socket ban and the cassette `record_mode="none"` are independent: even if a
test forgets to mock something, the socket ban still blocks the egress.
