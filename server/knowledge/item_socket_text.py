"""Remove only Rune declarations/effects for exact incremental item provenance checks."""

import re


def without_socketed_runes(raw: str) -> str:
    lines = str(raw or "").replace("\r\n", "\n").splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        value = lines[index].strip()
        if value.startswith("Sockets:") or value.startswith("Rune:"):
            index += 1
            continue
        if value.startswith("Implicits:"):
            try:
                count = int(value.split(":", 1)[1].strip())
            except ValueError:
                count = 0
            implicits = lines[index + 1 : index + 1 + count]
            kept = [line for line in implicits if not is_rune_effect_line(line)]
            if kept:
                output.append(f"Implicits: {len(kept)}")
                output.extend(kept)
            else:
                output.append("--------")
            index += 1 + count
            continue
        if not is_rune_effect_line(value):
            output.append(lines[index])
        index += 1
    return "\n".join(output)


def is_rune_effect_line(line: str) -> bool:
    return re.match(r"^(?:\{[^{}\r\n]+\})*\{rune\}", line.strip()) is not None
