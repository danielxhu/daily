"""`python -m app.doctor` advice mapping — pure function, offline. The probes
themselves hit the network and are not exercised here (netban suite)."""

from __future__ import annotations

from app.doctor import ProbeReport, advise


def test_foreign_datacenter_exit_names_the_split_tunnel_fix() -> None:
    report = ProbeReport(
        exit_ip="45.135.228.166",
        exit_country="SG",
        exit_org="AS199524 G-Core Labs S.A.",
        bilibili_status=412,
    )
    advice = "\n".join(advise(report))
    assert "数据中心" in advice and "分流" in advice
    assert "风控" in advice  # the 412 is named as risk control, with no bypass offered


def test_unreachable_youtube_points_at_the_tunnel() -> None:
    report = ProbeReport(
        exit_country="CN",
        exit_org="China Telecom",
        bilibili_status=200,
        youtube_error="[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred",
    )
    advice = "\n".join(advise(report))
    assert "YouTube" in advice and "代理" in advice


def test_healthy_exit_says_so() -> None:
    report = ProbeReport(
        exit_country="CN", exit_org="China Unicom", bilibili_status=200, youtube_status=200
    )
    assert advise(report) == ["出口看起来健康:国内外平台都可达,无风控迹象。"]
