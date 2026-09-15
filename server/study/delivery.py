"""Immutable educational files; publication never writes Research or learning memory."""

from __future__ import annotations

from pathlib import Path

from . import render, storage, icon_catalog, icons, component_icons
from .inline_names import InlineNames
from .models import StudyLesson
from .storage import StudyError


def publish(directory, lesson: StudyLesson, components: dict) -> dict:
    from .html_document import build_html

    digest = storage.fingerprint(lesson.model_dump())
    inline = InlineNames(
        component_icons.extend_catalog(
            icon_catalog.load_catalog(), components, lesson.guide.iconComponentRefs
        ),
        components,
        lesson.language,
        skill_refs=lesson.guide.iconSkillRefs,
        component_refs=lesson.guide.iconComponentRefs,
    )
    required = inline.required(lesson.guide, lesson.title)
    assets = icons.prepare(required, storage.root() / "icon-cache")
    module_dir = Path(__file__).parent
    renderer_hash = storage.fingerprint(
        {
            name: storage.fingerprint((module_dir / name).read_bytes())
            for name in (
                "render.py",
                "html_document.py",
                "templates/reader.css",
                "templates/reader.js",
                "component_icons.py",
                "data/unique_icons.json",
                "inline_names.py",
                "icons.py",
                "language.py",
            )
        }
    )
    icon_hash = storage.fingerprint(
        {identity: asset["sha256"] for identity, asset in assets.items()}
    )
    document_hash = storage.fingerprint(
        {"explanationHash": digest, "rendererHash": renderer_hash, "iconHash": icon_hash}
    )
    target = directory / "documents" / document_hash[:24]
    manifest_path = target / "manifest.json"
    if manifest_path.is_file():
        manifest = storage.read_json(manifest_path)
        if (
            manifest.get("explanationHash") != digest
            or manifest.get("rendererHash") != renderer_hash
            or manifest.get("documentHash") != document_hash
        ):
            raise StudyError("study_document_binding_invalid")
        expected = {
            "learning-guide.html",
            "learning-guide.md",
            *["assets/" + Path(a["path"]).name for a in assets.values()],
        }
        if set(manifest.get("hashes", {})) != expected:
            raise StudyError("study_document_binding_invalid")
        for name in expected:
            file = target / name
            if not file.is_file() or storage.fingerprint(file.read_bytes()) != manifest.get(
                "hashes", {}
            ).get(name):
                raise StudyError("study_document_integrity_failed")
    else:
        local_assets, asset_files = {}, {}
        for identity, asset in assets.items():
            data = Path(asset["path"]).read_bytes()
            if storage.fingerprint(data) != asset["sha256"]:
                raise StudyError("study_icon_integrity_failed")
            name = "assets/" + Path(asset["path"]).name
            storage.atomic_bytes(target / name, data)
            asset_files[name] = data
            local_assets[identity] = {**asset, "path": str((target / name).resolve())}
        inline.assets = local_assets
        arguments = dict(
            title=lesson.title, language=lesson.language, components=components, inline=inline
        )
        # Only the separately authored guide is passed to either renderer.
        files = {
            "learning-guide.md": render.markdown(lesson.guide, **arguments).encode("utf-8"),
            "learning-guide.html": build_html(lesson.guide, **arguments).encode("utf-8"),
            **asset_files,
        }
        manifest = {
            "schemaVersion": "study_document_v2",
            "explanationHash": digest,
            "rendererHash": renderer_hash,
            "documentHash": document_hash,
            "guideHash": storage.fingerprint(lesson.guide.model_dump()),
            "language": lesson.language,
            "icons": {
                identity: {k: a[k] for k in ("name", "iconPath", "bindingHash", "sha256", "url")}
                for identity, a in assets.items()
            },
            "hashes": {name: storage.fingerprint(value) for name, value in files.items()},
        }
        for name, value in files.items():
            storage.atomic_bytes(target / name, value)
        storage.atomic_json(manifest_path, manifest)
    return {
        "explanationHash": digest,
        "documentHash": document_hash,
        "guideHash": manifest["guideHash"],
        "iconCoverage": {
            "scope": "resolved_visual_identities",
            "required": len(required),
            "available": len(assets),
            "missing": 0,
        },
        "files": {
            name: {"path": str((target / name).resolve()), "sha256": digest}
            for name, digest in manifest["hashes"].items()
            if name in {"learning-guide.html", "learning-guide.md"}
        },
    }
