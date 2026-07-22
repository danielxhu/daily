"""Network-exit diagnosis — `python -m app.doctor` (owner 2026-07-21).

Lesson from steipete/summarize's `status --probe`: when sources fail, the cause
is usually the network SEAT, not the code — so probe the seat and say so in
plain words. The 2026-07-21 audit found exactly that: the machine's exit was a
Singapore datacenter IP (TUN-mode VPN), bilibili risk-controls datacenter exits
(HTTP 412), and YouTube dies (TLS reset) whenever the tunnel is off — two
disjoint failure worlds that read as "everything randomly fails".

Owner-facing CLI, no UI surface. Probes use the SAME fetch policy as ingestion
(honest UA, no cookies, no proxy pickup) so the report reflects what the app
actually experiences. Read-only; sends four GETs total; never bypasses anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx

from app.ingestion.fetch_policy import httpx_client_kwargs

# org substrings that mean "hosting/datacenter, not a home line" — the exact
# signal platform risk control keys on (best-effort list, not exhaustive)
_DATACENTER_MARKERS = (
    "g-core",
    "gcore",
    "hosting",
    "datacamp",
    "digitalocean",
    "ovh",
    "hetzner",
    "linode",
    "vultr",
    "aws",
    "amazon",
    "google cloud",
    "alibaba cloud",
    "tencent cloud",
    "m247",
    "leaseweb",
    "cdn77",
)


@dataclass
class ProbeReport:
    """Raw probe facts (separated from advice so tests can drive `advise()`)."""

    exit_ip: str | None = None
    exit_country: str | None = None
    exit_org: str | None = None
    bilibili_status: int | None = None  # None = connection-level failure
    bilibili_error: str | None = None
    youtube_status: int | None = None
    youtube_error: str | None = None
    notes: list[str] = field(default_factory=list)


def _looks_datacenter(org: str | None) -> bool:
    if not org:
        return False
    lowered = org.lower()
    return any(marker in lowered for marker in _DATACENTER_MARKERS)


def probe() -> ProbeReport:
    """Four read-only GETs through the ingestion fetch policy."""
    report = ProbeReport()
    with httpx.Client(**httpx_client_kwargs()) as client:  # type: ignore[arg-type]
        try:
            info = client.get("https://ipinfo.io/json").json()
            report.exit_ip = info.get("ip")
            report.exit_country = info.get("country")
            report.exit_org = info.get("org")
        except Exception as exc:
            report.notes.append(f"exit-IP lookup failed: {exc}")
        try:
            report.bilibili_status = client.get("https://www.bilibili.com/").status_code
        except Exception as exc:
            report.bilibili_error = str(exc)
        try:
            report.youtube_status = client.get(
                "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            ).status_code
        except Exception as exc:
            report.youtube_error = str(exc)
    return report


def advise(report: ProbeReport) -> list[str]:
    """Plain-words conclusions from probe facts. Pure function (offline-testable)."""
    advice: list[str] = []
    if report.exit_country and report.exit_country != "CN" and _looks_datacenter(report.exit_org):
        advice.append(
            f"出口是境外数据中心 IP({report.exit_org},{report.exit_country})——"
            "国内平台(B 站/微博/抖音)会对这类出口风控。若在用 VPN,"
            "请开启分流规则让国内域名直连,不要全局代理。"
        )
    if report.bilibili_status in (412, 429) or (
        report.bilibili_error and "412" in report.bilibili_error
    ):
        advice.append(
            "B 站正在风控此出口(HTTP 412/429)。这不是代码问题,也不该绕过:"
            "换回国内直连路由后自然恢复;风控通常数小时内衰减。"
        )
    if report.youtube_status is None and report.youtube_error:
        advice.append(
            f"YouTube 不可达({report.youtube_error[:80]})——当前网络需要代理才能访问 "
            "YouTube;若刚关掉 VPN,这就是 YouTube 源失败的原因。"
        )
    if not advice:
        advice.append("出口看起来健康:国内外平台都可达,无风控迹象。")
    return advice


def main() -> None:
    report = probe()
    exit_desc = (
        f"{report.exit_ip or '未知'} ({report.exit_org or '?'}, {report.exit_country or '?'})"
    )
    bili = report.bilibili_status if report.bilibili_status is not None else report.bilibili_error
    ytb = report.youtube_status if report.youtube_status is not None else report.youtube_error
    print("== daily 网络出口诊断 ==")
    print(f"出口 IP:   {exit_desc}")
    print(f"B 站:      {bili}")
    print(f"YouTube:   {ytb}")
    for note in report.notes:
        print(f"注:        {note}")
    print("-- 结论 --")
    for line in advise(report):
        print(f"• {line}")
    print()
    print(json.dumps(report.__dict__, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
