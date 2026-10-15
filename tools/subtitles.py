"""Read WebVTT cues without inventing word timestamps."""
import html
import re
from pathlib import Path


def timestamp(value):
    parts = value.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid VTT timestamp: {value}")
    values = [float(p) for p in parts]
    return sum(v * 60 ** i for i, v in enumerate(reversed(values)))


def read_vtt(path):
    text = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n[ \t]*\n", text):
        lines = block.strip().splitlines()
        if not lines or lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        match = re.match(r"\s*(\S+)\s+-->\s+(\S+)", lines[timing])
        if not match:
            raise ValueError("Invalid VTT timing line")
        start, end = map(timestamp, match.groups())
        if not 0 <= start < end:
            raise ValueError("Invalid VTT cue interval")
        # VTT styling/voice/timestamp tags are presentation metadata, not spoken text.
        caption = html.unescape(re.sub(r"<[^>]*>", "", "\n".join(lines[timing + 1:])))
        if caption.strip():
            cues.append({"s": start, "e": end, "text": caption})
    if not cues:
        raise ValueError(f"No subtitle cues: {path}")
    return sorted(cues, key=lambda cue: cue["s"])
