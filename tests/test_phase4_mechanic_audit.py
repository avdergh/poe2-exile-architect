from __future__ import annotations

from scripts import run_phase4_deep_review_acceptance as acceptance


WIKI_REF = "poe2wiki:page:855:rev:130794"


def _review(*, wiki_status: str, decision: str, corroboration: list[str]) -> dict:
    return {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:mechanic-audit"},
        "deepResearchRecords": [
            {
                "sampleId": "case:mechanic-audit",
                "title": "转换链",
                "recordKind": "mechanic_chain",
                "safeEvidenceRef": "evidence:fixture",
                "components": [
                    {
                        "componentKey": "skill:FixturePlayer",
                        "candidateName": "Fixture",
                    }
                ],
            }
        ],
        "candidateReviews": [
            {
                "sampleId": "case:mechanic-audit",
                "title": "转换候选",
                "safeEvidenceRef": "evidence:fixture",
                "components": [],
            }
        ],
        "mechanicAudit": [
            {
                "claim": "该命中先进行技能固有转换，再处理其他来源转换。",
                "claimType": "conversion_or_transform",
                "affectedRecords": ["转换链"],
                "affectedCandidates": ["转换候选"],
                "wiki": {
                    "status": wiki_status,
                    "pageTitle": "Damage conversion",
                    "sourceRef": WIKI_REF,
                },
                "corroboration": corroboration,
                "decision": decision,
            }
        ],
    }


def test_mechanic_audit_injects_pinned_ref_into_linked_objects():
    prepared, diagnostics, deferred = acceptance._prepare_mechanic_audit(
        _review(
            wiki_status="supports",
            decision="keep",
            corroboration=["source_artifact", "pinned_pob_static"],
        )
    )

    assert deferred == []
    assert diagnostics["entryCount"] == 1
    assert diagnostics["pinnedRevisionCount"] == 1
    assert diagnostics["schemaIssueCount"] == 0
    assert diagnostics["liveEvidenceStatus"] == "complete"
    assert diagnostics["unauditedHighRiskRecordCount"] == 0
    assert WIKI_REF in prepared["deepResearchRecords"][0]["safeEvidenceRefs"]
    assert WIKI_REF in prepared["candidateReviews"][0]["safeEvidenceRefs"]


def test_mechanic_audit_defers_only_linked_objects_on_unresolved_conflict():
    prepared, diagnostics, deferred = acceptance._prepare_mechanic_audit(
        _review(
            wiki_status="contradicts",
            decision="keep",
            corroboration=["source_artifact"],
        )
    )

    assert prepared["deepResearchRecords"] == []
    assert prepared["candidateReviews"] == []
    assert diagnostics["schemaIssueCount"] == 0
    assert diagnostics["deferredObjectCount"] == 2
    assert {item["reason"] for item in deferred} == {"mechanic_evidence_conflict"}


def test_mechanic_audit_rejects_unpinned_wiki_evidence():
    review = _review(
        wiki_status="supports",
        decision="keep",
        corroboration=["source_artifact"],
    )
    review["mechanicAudit"][0]["wiki"]["sourceRef"] = (
        "https://www.poe2wiki.net/wiki/Damage_conversion"
    )

    prepared, diagnostics, deferred = acceptance._prepare_mechanic_audit(review)

    assert prepared["deepResearchRecords"] == []
    assert prepared["candidateReviews"] == []
    assert diagnostics["schemaIssueCount"] == 1
    assert {item["reason"] for item in deferred} == {"invalid_schema"}
    assert any(
        issue["path"] == "mechanicAudit[0].wiki.sourceRef"
        for issue in diagnostics["entries"][0]["validationIssues"]
    )


def test_mechanic_audit_does_not_accept_wiki_only_claims():
    prepared, diagnostics, deferred = acceptance._prepare_mechanic_audit(
        _review(wiki_status="supports", decision="keep", corroboration=[])
    )

    assert prepared["deepResearchRecords"] == []
    assert prepared["candidateReviews"] == []
    assert diagnostics["schemaIssueCount"] == 0
    assert {item["reason"] for item in deferred} == {"wiki_only_mechanic_claim"}


def test_mechanic_audit_reports_missing_high_risk_record_coverage_without_blocking():
    review = _review(
        wiki_status="supports",
        decision="keep",
        corroboration=["source_artifact"],
    )
    review["mechanicAudit"] = []

    prepared, diagnostics, deferred = acceptance._prepare_mechanic_audit(review)

    assert prepared["deepResearchRecords"][0]["title"] == "转换链"
    assert deferred == []
    assert diagnostics["liveEvidenceStatus"] == "not_requested"
    assert diagnostics["highRiskRecordCount"] == 1
    assert diagnostics["auditedHighRiskRecordCount"] == 0
    assert diagnostics["unauditedHighRiskRecordTitles"] == ["转换链"]
    assert diagnostics["advisories"] == [
        "Some mechanic_chain/resource_engine records were not referenced by mechanicAudit."
    ]


def test_mechanic_audit_warns_about_compound_wiki_page_queries():
    review = _review(
        wiki_status="unavailable",
        decision="keep",
        corroboration=["source_artifact"],
    )
    review["mechanicAudit"][0]["wiki"] = {
        "status": "unavailable",
        "pageTitle": "Alpha / Beta",
        "sourceRef": "",
    }

    _prepared, diagnostics, deferred = acceptance._prepare_mechanic_audit(review)

    assert deferred == []
    assert diagnostics["liveEvidenceStatus"] == "unavailable_or_unused"
    assert diagnostics["compoundWikiQueryCount"] == 1
    assert diagnostics["advisories"] == [
        "Mechanic audit was submitted without any revision-pinned poe2wiki evidence.",
        "Mechanic audit used compound wiki page titles; query one exact page per lookup.",
    ]
