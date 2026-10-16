"""Unit tests for the OpsPilot Web Modernization Interface and Conversion Service."""

from pathlib import Path
from opspilot.ui.converter_service import ConversionService


def test_conversion_service_with_payroll_cbl():
    """Verify that ConversionService processes PAYROLL.CBL and emits required analytics."""
    payroll_path = Path("examples/sample_legacy/PAYROLL.CBL")
    assert payroll_path.exists()
    content = payroll_path.read_text(encoding="utf-8")

    service = ConversionService()
    result = service.process_cobol("PAYROLL.CBL", content)

    # 1. Percentage converted
    stats = result["conversion_stats"]
    assert "overall_percentage" in stats
    assert stats["overall_percentage"] > 0
    assert "section_percentage" in stats
    assert "data_percentage" in stats

    # 2. Multi-agent vs single LLM comparison
    comp = result["comparison"]
    assert "headline_metrics" in comp
    assert len(comp["headline_metrics"]) >= 5
    assert any("Build Success" in m["metric"] for m in comp["headline_metrics"])
    assert any("AST" in m["metric"] for m in comp["headline_metrics"])

    # 3. Process unfolding timeline
    timeline = result["process_timeline"]
    assert len(timeline) == 4
    assert timeline[0]["phase_id"] == 1
    assert timeline[1]["phase_id"] == 2
    assert timeline[2]["phase_id"] == 3
    assert timeline[3]["phase_id"] == 4

    # 4. Diagnostics & failure notes
    diagnostics = result["diagnostics"]
    assert len(diagnostics) > 0
    for d in diagnostics:
        assert "severity" in d
        assert "problem" in d
        assert "suggested_adjustment" in d
