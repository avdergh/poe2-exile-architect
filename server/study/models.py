"""Research-depth analysis with a separately authored learning document."""

from __future__ import annotations
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .guide import LearningGuide
from .language import normalize_language

Text = Annotated[str, Field(min_length=1)]
Ref = Annotated[str, Field(min_length=1, max_length=180)]
CHAPTERS = (
    "overview",
    "offense",
    "rotation",
    "skills",
    "gear",
    "passives",
    "ascendancy",
    "resources",
    "defenses",
    "limitations",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Bilingual(StrictModel):
    """Small external-source review fields, independent of the explanation language."""

    en: Text
    zh: Text


class GemAnalysis(StrictModel):
    effectRole: Text
    levelQuality: Text
    application: Text
    targetRefs: list[Ref]


class Explanation(StrictModel):
    componentRef: Ref
    role: Text
    sourceFacts: list[Text] = Field(min_length=1)
    reasoning: Text
    synergies: list[Ref]
    conditions: Text
    tradeoffs: Text
    failureModes: Text
    gemAnalysis: GemAnalysis | None = None
    evidenceRefs: list[Ref] = Field(min_length=1)
    status: Literal["supported", "inferred", "unknown"]


class Chapter(StrictModel):
    key: Literal[
        "overview",
        "offense",
        "rotation",
        "skills",
        "gear",
        "passives",
        "ascendancy",
        "resources",
        "defenses",
        "limitations",
    ]
    paragraphs: list[Text] = Field(min_length=1)
    evidenceRefs: list[Ref] = Field(min_length=1)


class Mechanism(StrictModel):
    id: Ref
    chapter: Literal["offense", "rotation", "resources", "defenses"]
    title: Text
    chain: list[Text] = Field(min_length=2)
    componentRefs: list[Ref] = Field(min_length=1)
    scaling: Text
    conditions: Text
    tradeoffs: Text
    failureModes: Text
    evidenceRefs: list[Ref] = Field(min_length=1)
    status: Literal["supported", "inferred", "unknown"]


class SkillGroupReview(StrictModel):
    groupRef: Ref
    role: Text
    outputMode: Text
    sequence: Text
    supportLogic: Text
    conditions: Text
    failureModes: Text
    evidenceRefs: list[Ref] = Field(min_length=1)


class PassiveCluster(StrictModel):
    title: Text
    componentRefs: list[Ref] = Field(min_length=1)
    purpose: Text
    scaling: Text
    keyPointNotes: dict[Ref, Text]
    conditions: Text
    tradeoffs: Text
    evidenceRefs: list[Ref] = Field(min_length=1)


class PassivePlan(StrictModel):
    attributesSought: list[Text] = Field(min_length=1)
    pathLogic: Text
    clusters: list[PassiveCluster]


class DepthReview(StrictModel):
    causalChainsReviewed: Literal[True]
    eachSkillGroupReviewed: Literal[True]
    equipmentInteractionsReviewed: Literal[True]
    passivePrioritiesReviewed: Literal[True]
    gemDetailsReviewed: Literal[True]
    conditionsAndFailuresReviewed: Literal[True]
    officialTerminologyOnly: Literal[True]
    authorIntentNotInvented: Literal[True]
    noWholeCharacterMirror: Literal[True]
    summary: Text


class StudyLesson(StrictModel):
    schemaVersion: Literal["study_explanation_v5"]
    sourceHash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    language: Text
    title: Text
    chapters: list[Chapter]
    mechanisms: list[Mechanism] = Field(min_length=1)
    components: list[Explanation]
    skillGroups: list[SkillGroupReview]
    passivePlan: PassivePlan
    depthReview: DepthReview
    guide: LearningGuide

    @field_validator("language")
    @classmethod
    def explicit_language(cls, value):
        return normalize_language(value)

    @model_validator(mode="after")
    def complete_structure(self):
        if sorted(x.key for x in self.chapters) != sorted(CHAPTERS):
            raise ValueError("the analysis requires every topic exactly once")
        for values, key in (
            (self.components, "componentRef"),
            (self.skillGroups, "groupRef"),
            (self.mechanisms, "id"),
        ):
            ids = [getattr(x, key) for x in values]
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate explanation identifiers")
        return self
