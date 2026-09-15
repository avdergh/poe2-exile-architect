"""Language is chosen from the user's request by the Agent, never from PoB names."""

import re


def normalize_language(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value
    ):
        raise ValueError("study_language_tag_required")
    parts = value.split("-")
    primary = parts[0].lower()
    rest = [
        part.title() if len(part) == 4 else part.upper() if len(part) == 2 else part
        for part in parts[1:]
    ]
    tag = "-".join([primary, *rest])
    if tag in {"zh-CN", "zh-Hans", "zh-Hans-CN"}:
        return "zh"
    return tag


def localized_name(component: dict, language: str) -> str:
    names = component["name"]
    # Only identity-bound, reviewed translations may override the English source name.
    return names.get(normalize_language(language)) or names["en"]
