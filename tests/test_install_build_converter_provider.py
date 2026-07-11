from __future__ import annotations

import json
from pathlib import Path

from scripts import install_build_converter_provider as installer


def test_replaceable_provider_dir_requires_owned_marker(tmp_path: Path):
    target = tmp_path / "provider"
    target.mkdir()
    assert installer._replaceable_provider_dir(target) is False

    (target / "provider.json").write_text(
        json.dumps({"providerId": "someone-else"}), encoding="utf-8"
    )
    assert installer._replaceable_provider_dir(target) is False

    (target / "provider.json").write_text(
        json.dumps({"providerId": installer.PROVIDER_ID}), encoding="utf-8"
    )
    assert installer._replaceable_provider_dir(target) is True
