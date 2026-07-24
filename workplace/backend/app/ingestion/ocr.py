"""On-device image OCR (owner 2026-07-23 "看图也要做").

XHS 图文 notes carry most of their information inside text screenshots, so the
image-reading default is Apple's Vision framework: free, local, no API key, no
image ever leaves the machine, ~0.3-0.7s per screenshot with clean dense-中文
output (measured on the DeepSeek-语录 note). "能用代码不用模型" (§11).

This is the first `VisionClient` implementation; a hosted VL model (百炼 etc.)
can plug into the same seam later for images whose meaning is NOT text (charts,
photos). pyobjc is macOS-only and installed via the `[ocr]` extra — everything
is lazy-imported and `get_vision_client()` degrades to None elsewhere, so a
Linux server simply skips image reading (typed, visible in the note text).
"""

from __future__ import annotations

from app.clients.base import VisionClient
from app.core.config import get_settings

_OCR_LANGUAGES = ["zh-Hans", "zh-Hant", "en-US"]


class AppleVisionOCR:
    """`VisionClient` backed by macOS Vision (VNRecognizeTextRequest)."""

    def read_image(self, image: bytes) -> str:
        import Vision  # lazy: pyobjc, macOS-only ([ocr] extra)
        from Foundation import NSData

        nsdata = NSData.dataWithBytes_length_(image, len(image))
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(nsdata, None)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(_OCR_LANGUAGES)
        request.setUsesLanguageCorrection_(True)
        ok, _err = handler.performRequests_error_([request], None)
        if not ok:
            return ""
        lines: list[str] = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates and len(candidates):
                lines.append(str(candidates[0].string()))
        return "\n".join(lines).strip()


def _apple_vision_available() -> bool:
    try:
        import Vision  # noqa: F401 — probe only

        return True
    except Exception:
        return False


def get_vision_client() -> VisionClient | None:
    """The configured image reader, or None (image reading off/unavailable) —
    callers treat None as "skip images", never as an error."""
    if get_settings().image_ocr == "off":
        return None
    return AppleVisionOCR() if _apple_vision_available() else None
