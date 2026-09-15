"""Fetch only identity-bound game icons and recheck their content on every use."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import re
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from PIL import Image

from . import storage

ROOT_URL = "https://repoe-fork.github.io/poe2/"


class IconCoverageError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("study_icons_unavailable")


def icon_url(path):
    if not isinstance(path, str) or not re.fullmatch(
        r"Art/(?:2DArt/SkillIcons|2DItems)/(?:[A-Za-z0-9_ -]+/)*[A-Za-z0-9_ -]+\.dds", path
    ):
        return None
    return ROOT_URL + quote(path[:-4] + ".webp", safe="/")


def _download(url):
    with urlopen(
        Request(url, headers={"User-Agent": "ExileArchitect-Study/1.0"}), timeout=20
    ) as response:
        if urlparse(response.url).hostname != "repoe-fork.github.io" or not response.url.startswith(
            ROOT_URL
        ):
            raise ValueError("icon_redirect_rejected")
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("icon_too_large")
    return data


def fetch(entry: dict, cache) -> dict:
    key = entry["bindingHash"]
    # Keep Windows user-data paths below legacy path limits; full identity stays in metadata.
    image_path = cache / f"{key[:24]}.png"
    meta_path = cache / f"{key[:24]}.json"
    if meta_path.is_file() and image_path.is_file():
        meta = storage.read_json(meta_path)
        if (
            meta.get("bindingHash") == key
            and meta.get("identity") == entry["identity"]
            and meta.get("sha256") == storage.fingerprint(image_path.read_bytes())
        ):
            return {**meta, "path": str(image_path.resolve()), "status": "available"}
    url = icon_url(entry.get("iconPath"))
    if not url:
        return {
            "status": "unavailable",
            "reason": "no_exact_icon_path",
            "identity": entry["identity"],
            "name": entry["name"],
        }
    try:
        if entry.get("atlas"):
            from .passive_art import read_icon

            raw = read_icon(entry["atlas"])
            url = "pob-texture:" + entry["atlas"]["treeVersion"] + ":" + entry["atlas"]["file"]
        else:
            raw = _download(url)
        with Image.open(BytesIO(raw)) as original:
            if original.format not in {"PNG", "WEBP"} or not (
                0 < original.width <= 4096 and 0 < original.height <= 4096
            ):
                raise ValueError("icon_image_invalid")
            # Format conversion only: preserve pixels and transparency, never redraw game art.
            original.load()
            output = BytesIO()
            original.convert("RGBA").save(output, format="PNG")
            width, height = original.size
        png = output.getvalue()
        meta = {
            **entry,
            "url": url,
            "rawSha256": storage.fingerprint(raw),
            "sha256": storage.fingerprint(png),
            "width": width,
            "height": height,
        }
        storage.atomic_bytes(image_path, png)
        storage.atomic_json(meta_path, meta)
        return {**meta, "path": str(image_path.resolve()), "status": "available"}
    except (OSError, ValueError):
        return {
            "status": "unavailable",
            "reason": "exact_icon_fetch_failed",
            "identity": entry["identity"],
            "name": entry["name"],
        }


def prepare(entries: dict, cache) -> dict:
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda entry: fetch(entry, cache), entries.values()))
    missing = [r for r in results if r["status"] != "available"]
    if missing:
        raise IconCoverageError(missing)
    return {item["identity"]: item for item in results}
