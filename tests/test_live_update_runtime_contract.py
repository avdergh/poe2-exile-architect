from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from server import paths
from server.live import update


def _engine_archive() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("pob/pob_headless.lua", "-- replacement bridge\n")
        archive.writestr("pob/PathOfBuilding-PoE2/src/.keep", "")
        archive.writestr("pob/PathOfBuilding-PoE2/runtime/lua/.keep", "")
    return payload.getvalue()


def _make_runtime(root: Path) -> None:
    (root / "PathOfBuilding-PoE2" / "src").mkdir(parents=True)
    (root / "PathOfBuilding-PoE2" / "runtime" / "lua").mkdir(parents=True)
    (root / "pob_headless.lua").write_text("-- bundled bridge\n", encoding="utf-8")


class LiveUpdateRuntimeContractTests(unittest.TestCase):
    def test_update_check_compares_app_version_to_manifest_not_data_stamp(self) -> None:
        with mock.patch.object(
            update,
            "_fetch_manifest",
            return_value={"version": "0.5.1", "app_version": "0.1.61"},
        ), mock.patch.object(update, "installed_version", return_value="0.5.0"), mock.patch.object(
            paths,
            "bundle_app_version",
            return_value="0.1.60",
        ):
            result = update.check_for_updates()

        self.assertTrue(result["available"])
        self.assertTrue(result["mcpb_update_available"])
        self.assertEqual(result["app_version_installed"], "0.1.60")

    def test_replacement_engine_with_old_contract_is_rejected_before_download(self) -> None:
        manifest = {
            "version": "0.5.1",
            "app_version": "0.1.60",
            "engine_contract": paths.POB_RUNTIME_CONTRACT - 1,
            "engine": {"url": "memory://engine", "sha256": "unused"},
        }
        with tempfile.TemporaryDirectory() as temp_name, mock.patch.object(
            update,
            "_fetch_manifest",
            return_value=manifest,
        ), mock.patch.object(paths, "user_data_dir", return_value=Path(temp_name)), mock.patch.object(
            update,
            "_http",
        ) as http:
            result = update.apply_updates(force=True)

        self.assertFalse(result["updated"])
        self.assertIn("contract", result["error"])
        http.assert_not_called()

    def test_replacement_engine_without_app_version_is_rejected_before_download(self) -> None:
        manifest = {
            "version": "0.5.1",
            "engine_contract": paths.POB_RUNTIME_CONTRACT,
            "engine": {"url": "memory://engine", "sha256": "unused"},
        }
        with tempfile.TemporaryDirectory() as temp_name, mock.patch.object(
            update,
            "_fetch_manifest",
            return_value=manifest,
        ), mock.patch.object(paths, "user_data_dir", return_value=Path(temp_name)), mock.patch.object(
            update,
            "_http",
        ) as http:
            result = update.apply_updates(force=True)

        self.assertFalse(result["updated"])
        self.assertIn("app version", result["error"])
        http.assert_not_called()

    def test_contract_four_engine_persists_app_bound_compatibility_metadata(self) -> None:
        blob = _engine_archive()
        manifest = {
            "version": "0.5.1",
            "app_version": "0.1.60",
            "engine_contract": paths.POB_RUNTIME_CONTRACT,
            "engine": {
                "url": "memory://engine",
                "sha256": hashlib.sha256(blob).hexdigest(),
            },
        }
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            user_root = root / "user-data"
            bundle_root = root / "bundle"
            user_root.mkdir()
            _make_runtime(bundle_root / "pob")
            (bundle_root / "data").mkdir(parents=True)
            (bundle_root / "data" / "VERSION").write_text("0.5.0\n", encoding="utf-8")
            (bundle_root / "manifest.json").write_text(
                json.dumps({"version": "0.1.60"}),
                encoding="utf-8",
            )
            with mock.patch.object(
                update,
                "_fetch_manifest",
                return_value=manifest,
            ), mock.patch.object(paths, "BUNDLE_ROOT", bundle_root), mock.patch.object(
                paths,
                "user_data_dir",
                return_value=user_root,
            ), mock.patch.object(
                update,
                "_http",
                return_value=blob,
            ):
                result = update.apply_updates(force=True, validate_engine=lambda _path: None)

            metadata = json.loads(
                (user_root / "installed.json").read_text(encoding="utf-8")
            )
            self.assertTrue(result["updated"])
            self.assertEqual(metadata["engine_contract"], paths.POB_RUNTIME_CONTRACT)
            self.assertEqual(metadata["engine_app_version"], "0.1.60")
            self.assertTrue((user_root / "pob" / "pob_headless.lua").is_file())
            with mock.patch.object(paths, "BUNDLE_ROOT", bundle_root), mock.patch.object(
                paths,
                "user_data_dir",
                return_value=user_root,
            ):
                self.assertEqual(paths.pob_runtime_pair().source, "user-data")


if __name__ == "__main__":
    unittest.main()
