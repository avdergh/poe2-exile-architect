"""Synthetic sanitized fixtures for the Phase 1 benchmark."""

from __future__ import annotations

FIXTURES = [
    {
        "snapshotId": "phase1_invalid_socket",
        "build": {
            "class": "Mercenary",
            "ascendancy": "Witchhunter",
            "level": 90,
            "mainSkill": "Spark",
            "mainSkillGroup": [
                {"name": "Spark", "isSupport": False},
                {"name": "Fireball", "isSupport": False},
            ],
            "pointsUsed": 90,
            "pointsAvailable": 113,
            "treeVersion": "0_5",
            "latestTreeVersion": "0_5",
        },
        "metrics": {"TotalDPS": 500_000, "TotalEHP": 20_000},
        "defenses": {"resistances": {"fire": 75, "cold": 75, "lightning": 75, "chaos": 75}},
    },
    {
        "snapshotId": "phase1_legal_baseline",
        "build": {
            "class": "Mercenary",
            "ascendancy": "Witchhunter",
            "level": 90,
            "mainSkill": "Spark",
            "mainSkillGroup": [{"name": "Spark", "isSupport": False}],
            "pointsUsed": 90,
            "pointsAvailable": 113,
            "treeVersion": "0_5",
            "latestTreeVersion": "0_5",
        },
        "metrics": {
            "TotalDPS": 500_000,
            "PhysicalMaximumHitTaken": 10_000,
            "FireMaximumHitTaken": 10_000,
            "ColdMaximumHitTaken": 10_000,
            "LightningMaximumHitTaken": 10_000,
            "ChaosMaximumHitTaken": 10_000,
            "TotalEHP": 20_000,
        },
        "defenses": {"resistances": {"fire": 75, "cold": 75, "lightning": 75, "chaos": 75}},
    },
]
