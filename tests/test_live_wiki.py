from __future__ import annotations

import re

from server.live import wiki


def test_live_poe2wiki_lookup_returns_revision_pinned_provenance():
    """This intentionally calls the real poe2wiki MediaWiki API; do not mock it."""

    result = wiki.lookup_mechanic("Combo")

    assert result["available"] is True
    assert result["found"] is True
    assert result["title"] == "Combo"
    assert "tracked and consumed separately for each skill" in result["text"]
    assert result["excerptKind"] == "lead_and_early_sections"
    assert result["resultKind"] in {"direct", "redirect"}
    assert result["pageId"] > 0
    assert result["revisionId"] > 0
    assert result["revisionTimestamp"].endswith("Z")
    assert result["permanentUrl"] == (
        f"https://www.poe2wiki.net/index.php?oldid={result['revisionId']}"
    )
    assert result["sourceRef"] == (f"poe2wiki:page:{result['pageId']}:rev:{result['revisionId']}")
    assert re.fullmatch(r"poe2wiki:page:[1-9][0-9]*:rev:[1-9][0-9]*", result["sourceRef"])
    assert result["permanentUrl"] in result["attribution"]


def test_live_lookup_returns_search_candidates_without_promoting_first_hit(monkeypatch):
    monkeypatch.setattr(wiki, "_extract", lambda _topic: None)
    monkeypatch.setattr(
        wiki,
        "_api",
        lambda _params, timeout=12.0: {
            "query": {
                "search": [
                    {
                        "title": "Chaos Inoculation",
                        "pageid": 42,
                        "snippet": "Mentions <span class='searchmatch'>Mind Over Matter</span>.",
                    }
                ]
            },
            "continue": {"sroffset": 8},
        },
    )

    result = wiki.lookup_mechanic("Mind Over Matter")

    assert result["found"] is False
    assert result["resultKind"] == "search_candidates"
    assert result["candidates"] == [
        {
            "title": "Chaos Inoculation",
            "pageId": 42,
            "snippet": "Mentions Mind Over Matter.",
            "matchKind": "search_candidate",
        }
    ]
    assert result["continuation"] == {"cursor": 8}
