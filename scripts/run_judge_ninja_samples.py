"""Run Judge against layered poe.ninja samples for Phase 1 calibration.

This module keeps three responsibilities isolated:
- list discovery from poe.ninja build pages
- import-code extraction from rendered build pages
- Judge execution and self-consistency classification

Raw PoB codes and raw XML stay transient and are never written to the repo.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from server.knowledge import mature_ninja_payload  # noqa: E402
from server.judge import sample_audit  # noqa: E402
from server import paths  # noqa: E402
from scripts.run_judge_user_samples import evaluate_source  # noqa: E402

try:
    import blackboxprotobuf  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised by runtime path, not unit tests.
    blackboxprotobuf = None


CHARACTER_LINK = re.compile(
    r"/poe2/builds/(?P<league>[a-z0-9-]+)/character/(?P<account>[^\"'<>/?#]+)/(?P<name>[^\"'<>?#]+)",
    re.IGNORECASE,
)
DEFAULT_BUILD_LIST_URL = "https://poe.ninja/poe2/builds/{league_url}?max-level={max_level}"
NINJA_LIST_CHARACTER_WAIT_MS = 15_000
NINJA_DETAIL_IMPORT_WAIT_MS = 30_000
NINJA_NAVIGATION_TIMEOUT_MS = 45_000
NINJA_PLAYWRIGHT_PROCESS_TIMEOUT_SECONDS = 90
NODE_ENV = "POE2_RESEARCH_NODE"
PLAYWRIGHT_ENV = "POE2_RESEARCH_PLAYWRIGHT"
CHROMIUM_ENV = "POE2_RESEARCH_CHROMIUM"


class NinjaSampleError(RuntimeError):
    """Raised when poe.ninja sample discovery or extraction cannot continue."""


def extract_character_links_from_rendered_html(
    page_html: str, *, league_url: str
) -> list[dict[str, Any]]:
    if not isinstance(page_html, str) or not page_html.strip():
        raise NinjaSampleError("page_html_required")
    row_pattern = re.compile(
        r"<tr[^>]*>.*?<a href=\"(?P<href>/poe2/builds/"
        + re.escape(league_url)
        + r"/character/(?P<account>[^\"/]+)/(?P<name>[^\"?#]+)[^\"]*)\"[^>]*>.*?</a>.*?"
        r"<td[^>]*>.*?<div[^>]*>(?P<level>\d+)<img[^>]*alt=\"(?P<ascendancy>[^\"]+)\"",
        re.IGNORECASE | re.DOTALL,
    )
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for match in row_pattern.finditer(page_html):
        account = match.group("account")
        name = match.group("name")
        key = (account, name)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "account": account,
                "name": name,
                "ascendancy": match.group("ascendancy"),
                "level": int(match.group("level")),
                "url": f"https://poe.ninja{html.unescape(match.group('href'))}",
            }
        )
    if out:
        return out

    for match in CHARACTER_LINK.finditer(page_html):
        if match.group("league").lower() != league_url.lower():
            continue
        account = match.group("account")
        name = match.group("name")
        key = (account, name)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "account": account,
                "name": name,
                "url": f"https://poe.ninja{html.unescape(match.group(0))}",
            }
        )
    return out


def build_character_url(league_url: str, row: dict[str, Any]) -> str:
    return (
        "https://poe.ninja/poe2/builds/"
        f"{league_url}/character/{quote(str(row['account']))}/{quote(str(row['name']))}"
    )


def sample_rows(
    rows: list[dict[str, Any]],
    *,
    target_count: int,
    minimum_per_ascendancy: int = 2,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("ascendancy"))].append(row)
    for bucket_rows in buckets.values():
        bucket_rows.sort(key=lambda item: (-int(item.get("level") or 0), item.get("name") or ""))

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ascendancy in sorted(buckets):
        for row in buckets[ascendancy][:minimum_per_ascendancy]:
            key = (str(row["account"]), str(row["name"]))
            if key not in seen and len(selected) < target_count:
                selected.append(row)
                seen.add(key)

    if len(selected) >= target_count:
        return selected[:target_count]

    round_index = minimum_per_ascendancy
    while len(selected) < target_count:
        progressed = False
        for ascendancy in sorted(buckets):
            bucket = buckets[ascendancy]
            if round_index >= len(bucket):
                continue
            row = bucket[round_index]
            key = (str(row["account"]), str(row["name"]))
            if key not in seen:
                selected.append(row)
                seen.add(key)
                progressed = True
                if len(selected) >= target_count:
                    break
        if not progressed:
            break
        round_index += 1
    return selected


def extract_import_code_from_rendered_build_page(page_html: str) -> dict[str, Any]:
    return mature_ninja_payload.extract_import_code_from_rendered_html(page_html)


def extract_import_code_from_dom_snapshot(snapshot_text: str) -> dict[str, Any]:
    return mature_ninja_payload.extract_import_code_from_dom_snapshot(snapshot_text)


class PlaywrightHtmlDriver:
    def __init__(
        self,
        *,
        node_executable: str | Path | None = None,
        playwright_package_path: str | Path | None = None,
        chromium_path: str | Path | None = None,
    ) -> None:
        runtime = discover_playwright_runtime(
            node_executable=node_executable,
            playwright_package_path=playwright_package_path,
            chromium_path=chromium_path,
        )
        self.node_executable = str(runtime["nodeExecutable"])
        self.playwright_package_path = Path(runtime["playwrightPackagePath"])
        self.chromium_path = Path(runtime["chromiumPath"])

    def fetch_html(self, url: str) -> str:
        is_build_list = "/poe2/builds/" in url and "/character/" not in url
        script = f"""
const {{ chromium }} = require({json.dumps(str(self.playwright_package_path))});
(async () => {{
  const browser = await chromium.launch({{
    headless: true,
    executablePath: {json.dumps(str(self.chromium_path))}
  }});
  const page = await browser.newPage();
  await page.goto({json.dumps(url)}, {{
    waitUntil: 'commit',
    timeout: {NINJA_NAVIGATION_TIMEOUT_MS}
  }});
  if ({json.dumps(is_build_list)}) {{
    try {{
      await page.waitForSelector('a[href*="/character/"]', {{
        state: 'attached',
        timeout: {NINJA_LIST_CHARACTER_WAIT_MS}
      }});
    }} catch (err) {{
      if (err.name !== 'TimeoutError') throw err;
    }}
  }} else {{
    try {{
      await page.waitForSelector('input[aria-label="Import code for Path of Building"]', {{
        state: 'attached',
        timeout: {NINJA_DETAIL_IMPORT_WAIT_MS}
      }});
    }} catch (err) {{
      if (err.name !== 'TimeoutError') throw err;
    }}
  }}
  const html = await page.content();
  process.stdout.write(html);
  await browser.close();
}})().catch(err => {{
  process.stderr.write(String(err));
  process.exit(1);
}});
""".strip()
        try:
            completed = subprocess.run(
                [self.node_executable, "-e", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=NINJA_PLAYWRIGHT_PROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise NinjaSampleError("playwright_fetch_timed_out") from exc
        if completed.returncode != 0:
            raise NinjaSampleError(
                f"playwright_fetch_failed:{completed.stderr.strip() or completed.stdout.strip()}"
            )
        return completed.stdout


def discover_playwright_runtime(
    *,
    node_executable: str | Path | None = None,
    playwright_package_path: str | Path | None = None,
    chromium_path: str | Path | None = None,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Path]:
    """Resolve a compatible Node, Playwright package, and Chromium without fixed runtime hashes."""
    env = environ if environ is not None else os.environ
    home_dir = Path(home) if home is not None else Path.home()
    node_candidates = _path_candidates(node_executable, env.get(NODE_ENV))
    playwright_candidates = _path_candidates(playwright_package_path, env.get(PLAYWRIGHT_ENV))

    for runtime_bin in _codex_cua_runtime_bins(home_dir):
        node_candidates.append(runtime_bin / ("node.exe" if os.name == "nt" else "node"))
        playwright_candidates.append(runtime_bin / "node_modules" / "playwright")

    system_node = shutil.which("node")
    if system_node:
        node_candidates.append(Path(system_node))
        system_node_path = Path(system_node)
        playwright_candidates.extend(
            [
                system_node_path.parent / "node_modules" / "playwright",
                _REPO_ROOT / "node_modules" / "playwright",
            ]
        )

    chromium_candidates = _path_candidates(chromium_path, env.get(CHROMIUM_ENV))
    chromium_candidates.extend(_playwright_chromium_candidates(home_dir, env))

    node = _first_existing_file(node_candidates)
    playwright = _first_playwright_package(playwright_candidates)
    chromium = _first_existing_file(chromium_candidates)
    missing = []
    if node is None:
        missing.append(f"node ({NODE_ENV})")
    if playwright is None:
        missing.append(f"playwright package ({PLAYWRIGHT_ENV})")
    if chromium is None:
        missing.append(f"chromium executable ({CHROMIUM_ENV})")
    if missing:
        raise NinjaSampleError(
            "playwright_runtime_unavailable:missing="
            + ",".join(missing)
            + ";checked_codex_runtimes="
            + str(len(_codex_cua_runtime_bins(home_dir)))
        )
    return {
        "nodeExecutable": node,
        "playwrightPackagePath": playwright,
        "chromiumPath": chromium,
    }


def _codex_cua_runtime_bins(home: Path) -> list[Path]:
    if os.name == "nt":
        root = home / "AppData" / "Local" / "OpenAI" / "Codex" / "runtimes" / "cua_node"
    elif sys.platform == "darwin":
        root = (
            home / "Library" / "Application Support" / "OpenAI" / "Codex" / "runtimes" / "cua_node"
        )
    else:
        root = home / ".local" / "share" / "OpenAI" / "Codex" / "runtimes" / "cua_node"
    if not root.exists():
        return []
    bins = [path / "bin" for path in root.iterdir() if path.is_dir()]
    return sorted(bins, key=lambda path: path.parent.stat().st_mtime, reverse=True)


def _playwright_chromium_candidates(home: Path, environ: dict[str, str]) -> list[Path]:
    roots = []
    local_app_data = environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.append(Path(local_app_data) / "ms-playwright")
    roots.extend([home / "AppData" / "Local" / "ms-playwright", home / ".cache" / "ms-playwright"])
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        versions = sorted(
            (path for path in root.glob("chromium-*") if path.is_dir()),
            key=_playwright_version,
            reverse=True,
        )
        for version in versions:
            candidates.extend(
                [
                    version / "chrome-win64" / "chrome.exe",
                    version / "chrome-linux" / "chrome",
                    version / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
                    version
                    / "chrome-mac-arm64"
                    / "Chromium.app"
                    / "Contents"
                    / "MacOS"
                    / "Chromium",
                ]
            )
    return candidates


def _path_candidates(*values: str | Path | None) -> list[Path]:
    return [Path(value).expanduser() for value in values if value]


def _first_existing_file(candidates: list[Path]) -> Path | None:
    return next((path.resolve() for path in candidates if path.is_file()), None)


def _first_playwright_package(candidates: list[Path]) -> Path | None:
    return next(
        (
            path.resolve()
            for path in candidates
            if path.is_dir() and (path / "package.json").is_file() and (path / "index.js").is_file()
        ),
        None,
    )


def _playwright_version(path: Path) -> tuple[int, str]:
    match = re.search(r"(\d+)$", path.name)
    return (int(match.group(1)) if match else -1, path.name)


def evaluate_ninja_sample_row(
    row: dict[str, Any],
    *,
    league_url: str,
    browser_driver: Any,
    snapshot_id: str,
) -> dict[str, Any]:
    if browser_driver is None:
        raise NinjaSampleError("browser_driver_required")

    character_url = row.get("url") or build_character_url(league_url, row)
    page_html = browser_driver.fetch_html(str(character_url))
    extracted = extract_import_code_from_rendered_build_page(page_html)
    if not extracted.get("ok"):
        raise NinjaSampleError(f"import_code_not_found:{character_url}")

    result = evaluate_source(str(extracted["importCode"]), snapshot_id)
    result["ninjaSample"] = {
        "account": row.get("account"),
        "name": row.get("name"),
        "ascendancy": row.get("ascendancy"),
        "level": row.get("level"),
        "characterUrl": character_url,
        "pob2DeepLinkRef": extracted.get("pob2DeepLinkRef"),
    }
    return finalize_sample_classification(result)


def evaluate_ninja_sample_row_safely(
    row: dict[str, Any],
    *,
    league_url: str,
    browser_driver: Any,
    snapshot_id: str,
) -> dict[str, Any]:
    try:
        return evaluate_ninja_sample_row(
            row,
            league_url=league_url,
            browser_driver=browser_driver,
            snapshot_id=snapshot_id,
        )
    except Exception as exc:  # noqa: BLE001 - batch runner must not abort on one sample.
        return finalize_sample_classification(
            {
                "snapshotId": snapshot_id,
                "summary": {
                    "class": None,
                    "ascendancy": row.get("ascendancy"),
                    "mainSkill": None,
                    "level": row.get("level"),
                },
                "pass": False,
                "rewardEligible": False,
                "rewardStrength": "none",
                "hardFailures": ["pob_compute_failed"],
                "physicalInvalidFailures": [],
                "caveats": ["state_or_import_suspect_caveat", "source_data_problem_caveat"],
                "modelability": {
                    "status": "not_modelable",
                    "coreBlocked": True,
                    "failureCodes": ["pob_compute_failed"],
                    "caveats": [],
                },
                "aggregateScore": {"value": 0.0},
                "scoreVector": {
                    "offense": {"value": 0.0, "blocked": True},
                    "defense": {"value": 0.0, "blocked": True},
                    "recovery": {"value": 0.0, "blocked": True},
                    "mobility": {"value": 0.0, "blocked": True},
                },
                "errorKind": type(exc).__name__,
                "errorSummary": str(exc)[:240],
                "ninjaSample": {
                    "account": row.get("account"),
                    "name": row.get("name"),
                    "ascendancy": row.get("ascendancy"),
                    "level": row.get("level"),
                    "characterUrl": row.get("url") or build_character_url(league_url, row),
                },
                "finalClassification": "source_data_problem",
            }
        )


def finalize_sample_classification(sample: dict[str, Any]) -> dict[str, Any]:
    return sample_audit.finalize_sample_classification(sample)


def summarize_results(samples: list[dict[str, Any]]) -> dict[str, Any]:
    return sample_audit.summarize_results(samples)


def run_browser_sampled_rows(
    rows: list[dict[str, Any]],
    *,
    league_url: str,
    browser_driver: Any,
    snapshot_prefix: str = "ninja_sample",
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        result = evaluate_ninja_sample_row_safely(
            row,
            league_url=league_url,
            browser_driver=browser_driver,
            snapshot_id=f"{snapshot_prefix}_{idx:03d}",
        )
        samples.append(result)
    return {"samples": samples, "summary": summarize_results(samples)}


def _sanitize_ninja_report(report: dict[str, Any]) -> dict[str, Any]:
    samples = []
    for sample in report.get("samples") or []:
        score_breakdown = sample.get("scoreBreakdown") or {}
        offense = score_breakdown.get("offense") or {}
        defense_model = sample.get("defenseModel") or {}
        samples.append(
            {
                "snapshotId": sample.get("snapshotId"),
                "summary": sample.get("summary"),
                "pass": sample.get("pass"),
                "finalClassification": sample.get("finalClassification"),
                "scoreReviewNeeded": sample.get("scoreReviewNeeded"),
                "scoreReviewReasons": sample.get("scoreReviewReasons"),
                "aggregateScore": sample.get("aggregateScore"),
                "scoreVector": sample.get("scoreVector"),
                "offenseEvidence": {
                    "provenance": offense.get("provenance"),
                    "evidenceLevel": offense.get("evidenceLevel"),
                    "sourceMetricDetail": offense.get("sourceMetricDetail"),
                    "skillName": offense.get("skillName"),
                    "rawValue": offense.get("rawValue"),
                },
                "defenseModel": {
                    "poolModel": defense_model.get("poolModel"),
                    "confidence": defense_model.get("confidence"),
                },
                "hardFailures": sample.get("hardFailures"),
                "physicalInvalidFailures": sample.get("physicalInvalidFailures"),
                "caveats": sample.get("caveats"),
                "rewardEligible": sample.get("rewardEligible"),
                "rewardStrength": sample.get("rewardStrength"),
                "reproducibility": sample.get("reproducibility"),
                "ninjaSample": _safe_ninja_sample(sample.get("ninjaSample") or {}),
                "errorKind": sample.get("errorKind"),
            }
        )
    return {
        "summary": report.get("summary"),
        "samples": samples,
    }


def _safe_ninja_sample(value: dict[str, Any]) -> dict[str, Any]:
    character_url = str(value.get("characterUrl") or value.get("url") or "")
    row_identity = "|".join(
        str(value.get(key) or "") for key in ("account", "name", "characterUrl", "url")
    )
    return {
        "rowRef": _safe_ref(row_identity, prefix="ninja-row-hash") if row_identity else None,
        "ascendancy": value.get("ascendancy"),
        "level": value.get("level"),
        "characterUrlRef": _safe_ref(character_url, prefix="ninja-url-hash")
        if character_url
        else None,
        "pob2DeepLinkRef": value.get("pob2DeepLinkRef"),
    }


def _safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_safe_ninja_sample(row) for row in rows]


def _safe_ref(value: str, *, prefix: str) -> str:
    return f"{prefix}:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def write_sanitized_ninja_report(report: dict[str, Any], *, filename: str) -> Path:
    out_dir = paths.user_data_dir() / "runtime"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    out_path.write_text(
        json.dumps(_sanitize_ninja_report(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def write_dual_sanitized_ninja_reports(
    *,
    raw_report: dict[str, Any],
    final_report: dict[str, Any],
    stem: str,
) -> tuple[Path, Path]:
    raw_path = write_sanitized_ninja_report(raw_report, filename=f"{stem}_raw.json")
    final_path = write_sanitized_ninja_report(final_report, filename=f"{stem}_final.json")
    return raw_path, final_path


def write_combined_calibration_report(
    *,
    historical_report: dict[str, Any],
    ninja_raw_report: dict[str, Any],
    ninja_final_report: dict[str, Any],
    stem: str = "judge_phase1_calibration_116",
) -> tuple[Path, Path]:
    combined_raw = {
        "summary": {
            "historicalCount": len(historical_report.get("samples") or []),
            "ninjaCount": len(ninja_raw_report.get("samples") or []),
            "sampleCount": len(historical_report.get("samples") or [])
            + len(ninja_raw_report.get("samples") or []),
        },
        "samples": (historical_report.get("samples") or [])
        + (ninja_raw_report.get("samples") or []),
    }
    combined_final = {
        "summary": {
            "historicalCount": len(historical_report.get("samples") or []),
            "ninjaCount": len(ninja_final_report.get("samples") or []),
            "sampleCount": len(historical_report.get("samples") or [])
            + len(ninja_final_report.get("samples") or []),
        },
        "samples": (historical_report.get("samples") or [])
        + (ninja_final_report.get("samples") or []),
    }
    return write_dual_sanitized_ninja_reports(
        raw_report=combined_raw,
        final_report=combined_final,
        stem=stem,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league-url", default="runesofaldur")
    parser.add_argument("--max-level", type=int, default=98)
    parser.add_argument("--target-count", type=int, default=100)
    parser.add_argument("--minimum-per-ascendancy", type=int, default=2)
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args(argv)

    browser = PlaywrightHtmlDriver()
    build_list_url = DEFAULT_BUILD_LIST_URL.format(
        league_url=args.league_url, max_level=args.max_level
    )
    build_list_html = browser.fetch_html(build_list_url)
    discovered = extract_character_links_from_rendered_html(
        build_list_html, league_url=args.league_url
    )
    sampled = sample_rows(
        discovered,
        target_count=args.target_count,
        minimum_per_ascendancy=args.minimum_per_ascendancy,
    )
    if args.print_only:
        print(
            json.dumps(
                {
                    "buildListRef": _safe_ref(build_list_url, prefix="ninja-list-hash"),
                    "sampledRows": _safe_rows(sampled),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    report = run_browser_sampled_rows(
        sampled,
        league_url=args.league_url,
        browser_driver=browser,
    )
    final_samples = [
        sample_audit.finalize_sample_classification(sample) for sample in report["samples"]
    ]
    final_report = {
        "samples": final_samples,
        "summary": sample_audit.summarize_results(final_samples),
    }
    write_dual_sanitized_ninja_reports(
        raw_report=report,
        final_report=final_report,
        stem=f"judge_ninja_samples_{args.league_url}_{args.max_level}_{args.target_count}",
    )
    print(
        json.dumps(
            {
                "buildListRef": _safe_ref(build_list_url, prefix="ninja-list-hash"),
                "sampledRows": _safe_rows(sampled),
                "summary": final_report["summary"],
                "samples": _sanitize_ninja_report(final_report)["samples"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
