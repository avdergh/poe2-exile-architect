from __future__ import annotations

import pytest

from server.generation import delivery


@pytest.fixture(autouse=True)
def _published_poe_ninja_link(monkeypatch):
    monkeypatch.setattr(
        delivery.pob_sharing,
        "publish_final_pob_artifact",
        lambda artifact_id: {
            "status": "published",
            "artifactId": artifact_id,
            "url": "https://poe.ninja/poe2/pob/abc123",
        },
    )


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
    assert result["exportedCount"] == result["expectedCount"] == 4
    assert [item["artifactType"] for item in result["artifacts"]] == [
        "pob_xml",
        "pob_import_code",
        "official_build",
        "poe_ninja_pob",
    ]
    assert [item["status"] for item in result["artifacts"]] == [
        "exported",
        "exported",
        "exported",
        "published",
    ]
    assert result["artifacts"][3]["url"] == "https://poe.ninja/poe2/pob/abc123"
    assert result["publicExternalUpload"] is True
    assert result["externalUploadContainsPobMaterial"] is True
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
    assert result["exportedCount"] == 3
    assert result["runtimeCleanupReady"] is False
    assert result["artifacts"][2] == {
        "artifactType": "official_build",
        "status": "failed",
        "outputPath": None,
        "errorCode": "provider_conversion_failed",
        "warnings": [],
    }


def test_delivery_package_preserves_failed_poe_ninja_upload(monkeypatch):
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
            "status": "exported",
            "outputPath": "C:/exports/build.build",
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        delivery.pob_sharing,
        "publish_final_pob_artifact",
        lambda _artifact_id: {
            "status": "failed",
            "errorCode": "poe_ninja_upload_unavailable",
        },
    )

    result = delivery.export_final_build_package("final-build:test")

    assert result["status"] == "partial"
    assert result["exportedCount"] == 3
    assert result["expectedCount"] == 4
    assert result["runtimeCleanupReady"] is False
    assert result["artifacts"][3] == {
        "artifactType": "poe_ninja_pob",
        "status": "failed",
        "url": None,
        "errorCode": "poe_ninja_upload_unavailable",
        "provider": "poe.ninja",
        "publicExternalUpload": True,
    }
