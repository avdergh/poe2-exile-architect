"""ReportLab paragraph adapter that keeps a skill's final word with its icon."""

from reportlab.platypus import Paragraph as BaseParagraph
from reportlab.platypus.paragraph import _getFragWords, _processed_frags


class Paragraph(BaseParagraph):
    def breakLines(self, width):
        # ReportLab's regular splitter emits every image as an independent word, even inside
        # <nobr>. Merge only our nobr image with its preceding text word before line layout.
        if self.frags and not _processed_frags(self.frags):
            maximum = max(width) if isinstance(width, (tuple, list)) else width
            joined = []
            for word in _getFragWords(self.frags, maxWidth=maximum):
                image = word[1][0] if len(word) == 2 else None
                is_attached_image = (
                    image is not None
                    and getattr(image, "nobr", False)
                    and getattr(getattr(image, "cbDefn", None), "kind", None) == "img"
                )
                if is_attached_image and joined and joined[-1][1:]:
                    previous = joined.pop()
                    joined.append([previous[0] + word[0], *previous[1:], *word[1:]])
                else:
                    joined.append(word)
            self.frags = joined
        lines = super().breakLines(width)
        if lines.kind == 1 and getattr(self.style, "autoLeading", None) == "max":
            for line in lines.lines:
                if any(
                    getattr(getattr(f, "cbDefn", None), "kind", None) == "img" for f in line.words
                ):
                    # Give larger icons breathing room without loosening text-only lines.
                    line.ascent += 2
                    line.descent -= 2
        return lines
