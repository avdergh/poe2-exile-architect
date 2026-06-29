from __future__ import annotations

import importlib

import server.live.mature_source_probe as mature_source_probe


def test_compare_sources_returns_safe_probe_matrix():
    report = mature_source_probe.compare_sources(
        [
            {
                "sourceType": "poe_ninja",
                "shapeReport": {
                    "ok": False,
                    "responseShape": ["leagueBuilds"],
                    "unavailableReason": "ascendancy-only payload",
                    "rawContentPersisted": False,
                    "rawJson": '{"leagueBuilds":[...]}',
                },
                "discoverability": "high",
                "popularityTrust": "high",
                "payloadRichness": "low",
                "sanitizationBurden": "medium",
                "duplicationRisk": "medium",
                "browserDependence": "medium",
            },
            {
                "sourceType": "pobb_in",
                "shapeReport": {
                    "ok": True,
                    "responseShape": ["build"],
                    "rowShape": ["skills", "tree", "items"],
                    "rawContentPersisted": False,
                    "rawHtml": "<html>copyable build</html>",
                },
                "discoverability": "medium",
                "popularityTrust": "medium",
                "payloadRichness": "high",
                "sanitizationBurden": "high",
                "duplicationRisk": "high",
                "browserDependence": "low",
            },
        ]
    )

    assert report["ok"] is True
    assert report["recommended"] == {
        "discoverySource": "poe_ninja",
        "payloadSource": "pobb_in",
    }
    assert len(report["sources"]) == 2
    assert report["sources"][0]["shapeReport"]["responseShape"] == ["leagueBuilds"]
    assert "rawHtml" not in str(report)
    assert "rawJson" not in str(report)
    assert "copyable build" not in str(report)


def test_render_probe_report_omits_raw_content_and_recommends_roles():
    markdown = mature_source_probe.render_probe_report(
        {
            "ok": True,
            "sources": [
                {
                    "sourceType": "poe_ninja",
                    "shapeReport": {
                        "ok": False,
                        "unavailableReason": "ascendancy-only payload",
                        "rawJson": '{"should":"not leak"}',
                    },
                    "discoverability": "high",
                    "popularityTrust": "high",
                    "payloadRichness": "low",
                    "sanitizationBurden": "medium",
                    "duplicationRisk": "medium",
                    "browserDependence": "medium",
                },
                {
                    "sourceType": "pobb_in",
                    "shapeReport": {
                        "ok": True,
                        "rowShape": ["skills", "tree", "items"],
                        "rawHtml": "<html>should not leak</html>",
                    },
                    "discoverability": "medium",
                    "popularityTrust": "medium",
                    "payloadRichness": "high",
                    "sanitizationBurden": "high",
                    "duplicationRisk": "high",
                    "browserDependence": "low",
                },
            ],
            "recommended": {
                "discoverySource": "poe_ninja",
                "payloadSource": "pobb_in",
            },
        }
    )

    assert "# 成熟样本源探测报告" in markdown
    assert "推荐的热门发现源" in markdown
    assert "推荐的 payload 源" in markdown
    assert "`poe_ninja`" in markdown
    assert "`pobb_in`" in markdown
    assert "discoverySource" not in markdown
    assert "payloadSource" not in markdown
    assert "rawHtml" not in markdown
    assert "rawJson" not in markdown
    assert "should not leak" not in markdown


def test_compare_sources_skips_payload_recommendation_when_all_shapes_fail():
    report = mature_source_probe.compare_sources(
        [
            {
                "sourceType": "poe_ninja",
                "shapeReport": {
                    "ok": False,
                    "unavailableReason": "aggregate-only payload",
                },
                "discoverability": "high",
                "popularityTrust": "high",
                "payloadRichness": "medium",
            },
            {
                "sourceType": "pobb_in",
                "shapeReport": {
                    "ok": False,
                    "unavailableReason": "browser-only page shell",
                },
                "discoverability": "medium",
                "popularityTrust": "medium",
                "payloadRichness": "high",
            },
        ]
    )

    assert report["ok"] is True
    assert report["recommended"]["discoverySource"] == "poe_ninja"
    assert report["recommended"]["payloadSource"] is None


def test_compare_sources_tolerates_missing_fields_and_unknown_levels():
    report = mature_source_probe.compare_sources(
        [
            {
                "shapeReport": "not-a-mapping",
                "discoverability": "unexpected",
            }
        ]
    )

    assert report["ok"] is True
    assert report["sources"] == [
        {
            "sourceType": "unknown",
            "shapeReport": {},
            "discoverability": "unknown",
            "popularityTrust": "unknown",
            "payloadRichness": "unknown",
            "sanitizationBurden": "unknown",
            "duplicationRisk": "unknown",
            "browserDependence": "unknown",
        }
    ]
    assert report["recommended"]["discoverySource"] == "unknown"
    assert report["recommended"]["payloadSource"] is None


def test_render_probe_report_handles_raw_key_variants_and_string_shapes():
    markdown = mature_source_probe.render_probe_report(
        {
            "sources": [
                {
                    "sourceType": "external",
                    "shapeReport": {
                        "ok": True,
                        "responseShape": "builds",
                        "rowShape": "items",
                        "raw_html": "<html>should not leak</html>",
                        "RawJson": '{"should":"not leak"}',
                    },
                }
            ],
            "recommended": {
                "discoverySource": "external",
                "payloadSource": "external",
            },
        }
    )

    assert "响应结构：builds" in markdown
    assert "响应结构：b, u, i, l, d, s" not in markdown
    assert "行结构：items" in markdown
    assert "行结构：i, t, e, m, s" not in markdown
    assert "raw_html" not in markdown
    assert "RawJson" not in markdown
    assert "should not leak" not in markdown


def test_cli_main_writes_probe_report_and_prints_chinese_confirmation(
    tmp_path, monkeypatch, capsys
):
    cli = importlib.import_module("scripts.run_mature_source_probe")
    output_path = tmp_path / "mature_source_probe_report.md"

    monkeypatch.setattr(cli, "DEFAULT_OUTPUT_PATH", output_path)
    monkeypatch.setattr(cli, "_default_probe_rows", lambda: [{"sourceType": "stub"}])

    def fake_compare_sources(rows):
        assert rows == [{"sourceType": "stub"}]
        return {"ok": True, "recommended": {"discoverySource": "stub", "payloadSource": None}}

    monkeypatch.setattr(cli.mature_source_probe, "compare_sources", fake_compare_sources)
    monkeypatch.setattr(
        cli.mature_source_probe,
        "render_probe_report",
        lambda report: "# 成熟样本源探测报告\n\nstub",
    )

    assert cli.main() == 0

    output = capsys.readouterr().out
    assert f"探测报告已写入 {output_path}" in output
    assert output_path.read_text(encoding="utf-8") == "# 成熟样本源探测报告\n\nstub"
