"""Shared versioned Research contracts.

This module contains only stable, copy-safe constants used by the Research packet,
review, durable-memory, query, and generation provenance layers.  Keeping these
values in one place prevents the public contracts from drifting independently.
"""

from __future__ import annotations


RESEARCH_MEMORY_DB_SCHEMA_VERSION = 5
SAFE_REVIEW_CONTRACT_VERSION = "phase4-safe-review-v3"
LEGACY_SAFE_REVIEW_CONTRACT_VERSION = "phase4-safe-review-v2"
NEW_DEEP_RESEARCH_OUTPUT_SCHEMA_VERSION = 6
NEW_DEEP_RECORD_SCHEMA_VERSION = 2
LEGACY_DEEP_RESEARCH_OUTPUT_SCHEMA_VERSION = 5
LEGACY_DEEP_RECORD_SCHEMA_VERSION = 1

QUERY_CONTRACT_VERSION = 2
VALIDATION_ISSUE_CONTRACT_VERSION = 2
RESEARCH_QUERY_RESPONSE_BUDGET_BYTES = 65_536

SOURCE_STATE_SCOPES = {
    "active_state",
    "alternate_weapon_state",
    "state_agnostic",
    "unknown",
}
CREATE_AUTHORIZING_SOURCE_STATE_SCOPES = {"active_state", "state_agnostic"}

GEAR_SUBJECTS = {
    "weapon",
    "offhand_or_quiver",
    "helmet",
    "body_armour",
    "gloves",
    "boots",
    "belt",
    "amulet",
    "ring",
    "flask",
    "charm",
    "passive_tree_jewel",
    "embedded_item_jewel",
}

SUPPORT_DELIVERY_ROLES = {
    "direct",
    "trigger_host",
    "triggered_payload",
    "proxy_host",
    "proxy_payload",
}

KNOWN_RESEARCH_REPAIR_ID = "research_known_semantic_repair_20260822_v1"
KNOWN_BAD_RESEARCH_RECORDS = (
    {
        "recordId": "drr-3c7af3648e52eff8",
        "knowledgeKey": "ku-0c734e830a422a98a769",
        "recordKind": "gear_synergy",
        "projectionHash": "f7ebb2622bb11fbed15924d5928cd33c70ec4b7a8954050421a0bae8f5201f85",
        "sourceCaseRefs": ["source-hash:953d020627f0cc5c"],
    },
    {
        "recordId": "drr-3af552945180d0ac",
        "knowledgeKey": "ku-b723697d22ec241d4070",
        "recordKind": "defense_engine",
        "projectionHash": "f5c290e9f7e0e5c5a1e6cd6cc18d2b924087c0420aec629edc3c8bbe70b10b3f",
        "sourceCaseRefs": ["source-hash:c5c603213cd2f5bf"],
    },
    {
        "recordId": "drr-a2ba964c89de75b0",
        "knowledgeKey": "ku-aa0f0964eb361b7d98d5",
        "recordKind": "gear_synergy",
        "projectionHash": "436d0b168698af60bcc0495b44837be6a2f8d1d75f3210709d3efd546da7640c",
        "sourceCaseRefs": ["source-hash:16d58adff7c76899"],
    },
    {
        "recordId": "drr-eaedc172dcb22ea5",
        "knowledgeKey": "ku-e39f327165c0360150cc",
        "recordKind": "defense_engine",
        "projectionHash": "ae378290ea031c8c19e047487a9bad1ae308cb1227e7df199d9112e29f2b17e6",
        "sourceCaseRefs": ["source-hash:16d58adff7c76899"],
    },
    {
        "recordId": "drr-1f3cf86180f59a5a",
        "knowledgeKey": "ku-68a6d634854c9066903d",
        "recordKind": "modelability_caveat",
        "projectionHash": "ad7075eebf344d9ba49b83aef9c3907cb59f24d4d70cc8e81b22474150eb634a",
        "sourceCaseRefs": ["source-hash:16d58adff7c76899"],
    },
)
