from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from server import paths
from server.compute.engine import PobEngine


def _make_runtime(root: Path) -> None:
    (root / "PathOfBuilding-PoE2" / "src").mkdir(parents=True)
    (root / "PathOfBuilding-PoE2" / "runtime" / "lua").mkdir(parents=True)
    (root / "pob_headless.lua").write_text("-- test bridge\n", encoding="utf-8")


class PobRuntimeSelectionTests(unittest.TestCase):
    def _select(self, *, contract: int, engine_version: str) -> str:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            bundle_root = root / "bundle"
            user_root = root / "user-data"
            _make_runtime(bundle_root / "pob")
            _make_runtime(user_root / "pob")
            (bundle_root / "data").mkdir(parents=True)
            (bundle_root / "data" / "VERSION").write_text(
                "0.5.0+codex.20260830170724\n",
                encoding="utf-8",
            )
            (bundle_root / "manifest.json").write_text(
                json.dumps({"version": "0.1.60"}),
                encoding="utf-8",
            )
            (user_root / "installed.json").write_text(
                json.dumps(
                    {
                        "engine_contract": contract,
                        "engine_app_version": engine_version,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(paths, "BUNDLE_ROOT", bundle_root), mock.patch.object(
                paths,
                "user_data_dir",
                return_value=user_root,
            ):
                return paths.pob_runtime_pair().source

    def test_contract_three_is_rejected_even_when_its_version_is_newer(self) -> None:
        self.assertEqual(
            self._select(
                contract=3,
                engine_version="99.0.0",
            ),
            "bundle",
        )

    def test_contract_four_without_passive_attributes_and_jewel_observation_is_rejected(self) -> None:
        self.assertEqual(
            self._select(contract=4, engine_version="99.0.0"),
            "bundle",
        )

    def test_contract_five_without_complete_item_replacement_is_rejected(self) -> None:
        self.assertEqual(
            self._select(contract=5, engine_version="99.0.0"),
            "bundle",
        )

    def test_current_contract_still_requires_a_current_engine_version(self) -> None:
        self.assertEqual(
            self._select(
                contract=paths.POB_RUNTIME_CONTRACT,
                engine_version="0.1.59",
            ),
            "bundle",
        )

    def test_current_contract_runtime_can_override_the_bundle(self) -> None:
        self.assertEqual(
            self._select(
                contract=paths.POB_RUNTIME_CONTRACT,
                engine_version="0.1.60",
            ),
            "user-data",
        )

    def test_missing_bundle_app_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            bundle_root = root / "bundle"
            user_root = root / "user-data"
            _make_runtime(bundle_root / "pob")
            _make_runtime(user_root / "pob")
            (user_root / "installed.json").write_text(
                json.dumps(
                    {
                        "engine_contract": paths.POB_RUNTIME_CONTRACT,
                        "engine_app_version": "99.0.0",
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(paths, "BUNDLE_ROOT", bundle_root), mock.patch.object(
                paths,
                "user_data_dir",
                return_value=user_root,
            ):
                self.assertEqual(paths.pob_runtime_pair().source, "bundle")

    def test_bundled_bridge_advertises_native_defense_contract(self) -> None:
        engine = PobEngine()
        try:
            self.assertEqual(engine.info["runtimeContract"], paths.POB_RUNTIME_CONTRACT)
            self.assertEqual(paths.POB_RUNTIME_CONTRACT, 8)
        finally:
            engine.close()

    def test_app_and_data_versions_are_independent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (root / "manifest.json").read_text(encoding="utf-8")
        )
        data_version = (root / "data" / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(paths.bundle_app_version(), manifest["version"])
        self.assertNotEqual(data_version, manifest["version"])


if __name__ == "__main__":
    unittest.main()
