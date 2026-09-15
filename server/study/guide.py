"""Learner-facing editorial model, independent of Research's analysis records."""

from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1)]


class GuideModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Paragraph(GuideModel):
    type: Literal["paragraph"]
    text: Text


class Heading(GuideModel):
    type: Literal["heading"]
    text: Text


class BulletList(GuideModel):
    type: Literal["bullets"]
    items: list[Text] = Field(min_length=1)


class Comparison(GuideModel):
    type: Literal["table"]
    columns: list[Text] = Field(min_length=2, max_length=4)
    rows: list[list[Text]] = Field(min_length=1)

    @model_validator(mode="after")
    def rectangular(self):
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("comparison rows must match their columns")
        return self


class FlowStep(GuideModel):
    label: Text
    explanation: Text


class MechanismFlow(GuideModel):
    type: Literal["flow"]
    title: Text
    steps: list[FlowStep] = Field(min_length=2, max_length=6)


class TeachingNote(GuideModel):
    type: Literal["note"]
    kind: Literal["remember", "practice", "check"]
    title: Text
    text: Text


Block = Annotated[
    Paragraph | Heading | BulletList | Comparison | MechanismFlow | TeachingNote,
    Field(discriminator="type"),
]


class LearningUnit(GuideModel):
    title: Text
    introduction: Text
    blocks: list[Block] = Field(min_length=1)
    startNewPage: bool = False
    # These associations are checked internally and never printed as learner prose.
    topics: list[Text] = Field(min_length=1)
    componentRefs: list[Text]
    groupRefs: list[Text]
    mechanismRefs: list[Text]


class TeachingReview(GuideModel):
    languageConsistent: Literal[True]
    readerJourneyReviewed: Literal[True]
    detailPreserved: Literal[True]
    conditionsExplainedInContext: Literal[True]
    visualsExplainRelationships: Literal[True]
    noAuditDump: Literal[True]
    summary: Text


class ReaderUI(GuideModel):
    searchPlaceholder: Text
    clearSearch: Text
    noResults: Text
    showAll: Text
    componentDetails: Text
    closeDetails: Text
    jumpToExplanation: Text
    helpText: Text
    kindLabels: dict[Text, Text]

    @model_validator(mode="after")
    def complete_labels(self):
        required = {
            "active",
            "skill",
            "support",
            "granted_skill",
            "gear",
            "unique",
            "passive",
            "ascendancy",
            "socketable",
            "concept",
            "item_base",
        }
        if not required <= set(self.kindLabels):
            raise ValueError("reader labels must cover every entity category")
        return self


class Concept(GuideModel):
    term: Text
    category: Text | None = None
    explanation: Text


class LearningGuide(GuideModel):
    reader: ReaderUI
    navigationTitle: Text
    iconSkillRefs: list[Text] = Field(default_factory=list)
    iconComponentRefs: list[Text] = Field(default_factory=list)
    componentNotes: dict[Text, Text] = Field(default_factory=dict)
    concepts: list[Concept] = Field(default_factory=list)
    subtitle: Text
    introduction: Text
    chatIntroduction: Text
    units: list[LearningUnit] = Field(min_length=1)
    teachingReview: TeachingReview


def coverage_issues(guide: LearningGuide, *, components, groups, mechanisms, topics):
    issues = []
    for field, expected in (
        ("componentRefs", set(components)),
        ("groupRefs", set(groups)),
        ("mechanismRefs", set(mechanisms)),
        ("topics", set(topics)),
    ):
        covered = {ref for unit in guide.units for ref in getattr(unit, field)}
        if covered != expected:
            issues.append(
                {
                    "code": "study_guide_coverage_incomplete",
                    "field": field,
                    "missing": sorted(expected - covered),
                    "extra": sorted(covered - expected),
                }
            )
    if not any(block.type == "flow" for unit in guide.units for block in unit.blocks):
        issues.append({"code": "study_guide_mechanism_visual_required"})
    return issues
