from __future__ import annotations

from server.generation import delivery


def test_delivery_package_lists_all_expected_artifacts(monkeypatch):
    marked = []
    monkeypatch.setattr(
        delivery.artifacts,
        "mark_final_build_delivery_complete",
        lambda artifact_id: marked.append(artifact_id) or True,
    )
    monkeypatch.setattr(
        delivery.pob_exports,
        "export_final_pob_artifact",
        lambda *args, **kwargs: {
            "status": "exported",
            "outputs": [
                {"format": "xml", "outputPath": "C:/exports/build.xml"},
                {"format": "import_code", "outputPath": "C:/exports/build.pobcode.txt"},
            ],
        },
    )
    monkeypatch.setattr(
        delivery.build_planner_exporter,
        "export_final_build_artifact",
        lambda *args, **kwargs: {
            "status": "exported",
            "outputPath": "C:/exports/build.build",
            "warnings": [],
        },
    )

    result = delivery.export_final_build_package("final-build:test", name="Test")

    assert result["status"] == "exported"
    assert result["exportedCount"] == result["expectedCount"] == 3
    assert [item["artifactType"] for item in result["artifacts"]] == [
        "pob_xml",
        "pob_import_code",
        "official_build",
    ]
    assert all(item["status"] == "exported" for item in result["artifacts"])
    assert result["runtimeCleanupReady"] is True
    assert marked == ["final-build:test"]


def test_delivery_package_preserves_failed_build_export(monkeypatch):
    monkeypatch.setattr(
        delivery.artifacts,
        "mark_final_build_delivery_complete",
        lambda _artifact_id: (_ for _ in ()).throw(AssertionError("must not mark partial export")),
    )
    monkeypatch.setattr(
        delivery.pob_exports,
        "export_final_pob_artifact",
        lambda *args, **kwargs: {
            "status": "exported",
            "outputs": [
                {"format": "xml", "outputPath": "C:/exports/build.xml"},
                {"format": "import_code", "outputPath": "C:/exports/build.pobcode.txt"},
            ],
        },
    )
    monkeypatch.setattr(
        delivery.build_planner_exporter,
        "export_final_build_artifact",
        lambda *args, **kwargs: {
            "status": "error",
            "errorCode": "provider_conversion_failed",
        },
    )

    result = delivery.export_final_build_package("final-build:test")

    assert result["status"] == "partial"
    assert result["exportedCount"] == 2
    assert result["runtimeCleanupReady"] is False
    assert result["artifacts"][2] == {
        "artifactType": "official_build",
        "status": "failed",
        "outputPath": None,
        "errorCode": "provider_conversion_failed",
        "warnings": [],
    }
