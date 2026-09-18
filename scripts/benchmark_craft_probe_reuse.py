"""Compare bounded craft search orchestration with a fixed oracle (not a PoB speed claim).

Run this same script in separate processes with --repo pointing to old/new checkouts.
Only --scratch is writable; no saved character, service, or active PoB is opened.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    scratch = args.scratch.resolve()
    if scratch == repo or repo in scratch.parents:
        # The new checkout's explicit .test-tmp directory is safe; source/data is not.
        if ".test-tmp" not in scratch.relative_to(repo).parts:
            parser.error("scratch under the checkout must be inside .test-tmp")
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ["POE2_MCP_DATA"] = str(scratch)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(repo))
    import pytest
    from tests.test_craft_search_contract import craft_fixture
    from server.compute import craftopt

    rows = []
    for candidate_count, sockets in [(1, 1), (12, 1), (12, 2)]:
        with pytest.MonkeyPatch.context() as patch:
            engine, original, receipts = craft_fixture.__wrapped__(patch)
            engine.options["runes"] = [
                {"name": f"Fixture Rune {index:02}", "mods": ["+20 to Armour"]}
                for index in range(candidate_count)
            ]
            candidate_hashes = []
            original_eval = engine.eval_items

            def measured(slot, items, keys, **kwargs):
                candidate_hashes.extend(hashlib.sha256(text.encode()).hexdigest() for text in items)
                return original_eval(slot, items, keys, **kwargs)

            engine.eval_items = measured
            started = time.perf_counter()
            result = craftopt.craft_item(
                engine, "Body Armour", metric="TotalEHP", rune_sockets=sockets
            )
            rows.append(
                {
                    "candidateCount": candidate_count,
                    "socketCount": sockets,
                    "elapsedSeconds": round(time.perf_counter() - started, 6),
                    "evalBatches": engine.batch_count,
                    "candidateProbes": len(candidate_hashes),
                    "distinctCandidateTexts": len(set(candidate_hashes)),
                    "ok": result.get("ok"),
                    "errorCode": result.get("errorCode"),
                    "finalMetric": result.get("metricAfter"),
                    "itemFingerprint": hashlib.sha256(
                        str(result.get("item", "")).encode()
                    ).hexdigest(),
                    "restored": engine.get_xml() == original,
                    "receiptCount": len(receipts),
                }
            )
    print(json.dumps({"mode": "fixed_oracle_not_real_pob", "scenarios": rows}, indent=2))


if __name__ == "__main__":
    main()
