#!/usr/bin/env python3
"""Retime an SRT file by a constant playback speed."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


TIMING_RE = re.compile(
    r"^(?P<start>\d{2,}:[0-5]\d:[0-5]\d,\d{3})"
    r"\s+-->\s+"
    r"(?P<end>\d{2,}:[0-5]\d:[0-5]\d,\d{3})"
    r"(?P<settings>\s+.*)?$"
)


@dataclass(frozen=True)
class Cue:
    index: int
    start_ms: int
    end_ms: int
    settings: str
    text_lines: tuple[str, ...]


def timestamp_to_ms(value: str) -> int:
    hours, minutes, rest = value.split(":")
    seconds, milliseconds = rest.split(",")
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        + int(milliseconds)
    )


def ms_to_timestamp(value: int) -> str:
    hours, remainder = divmod(value, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def parse_srt(text: str) -> list[Cue]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not normalized:
        raise ValueError("SRT file is empty")

    cues: list[Cue] = []
    for block_number, block in enumerate(
        re.split(r"\n[ \t]*\n+", normalized), start=1
    ):
        lines = block.split("\n")
        if len(lines) < 3:
            raise ValueError(f"cue block {block_number} must contain an index, timing, and text")
        try:
            index = int(lines[0].strip())
        except ValueError as exc:
            raise ValueError(f"cue block {block_number} has a non-numeric index") from exc
        match = TIMING_RE.fullmatch(lines[1].strip())
        if not match:
            raise ValueError(f"cue {index} has an invalid timing line: {lines[1]!r}")
        if not any(line.strip() for line in lines[2:]):
            raise ValueError(f"cue {index} has no subtitle text")
        cues.append(
            Cue(
                index=index,
                start_ms=timestamp_to_ms(match.group("start")),
                end_ms=timestamp_to_ms(match.group("end")),
                settings=match.group("settings") or "",
                text_lines=tuple(lines[2:]),
            )
        )
    validate_cues(cues, "input")
    return cues


def validate_cues(cues: list[Cue], label: str) -> None:
    previous_start = -1
    previous_end = -1
    for expected_index, cue in enumerate(cues, start=1):
        if cue.index != expected_index:
            raise ValueError(
                f"{label}: cue indices must be sequential from 1; "
                f"expected {expected_index}, got {cue.index}"
            )
        if cue.start_ms >= cue.end_ms:
            raise ValueError(
                f"{label}: cue {cue.index} must satisfy start < end "
                f"({ms_to_timestamp(cue.start_ms)} >= {ms_to_timestamp(cue.end_ms)})"
            )
        if cue.start_ms <= previous_start or cue.end_ms <= previous_end:
            raise ValueError(f"{label}: cue times must be strictly increasing at cue {cue.index}")
        if previous_end >= 0 and cue.start_ms < previous_end:
            raise ValueError(f"{label}: cue {cue.index} overlaps the previous cue")
        previous_start = cue.start_ms
        previous_end = cue.end_ms


def retime(cues: list[Cue], speed: Decimal) -> list[Cue]:
    def scaled(value: int) -> int:
        return int((Decimal(value) / speed).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    result = [
        Cue(
            index=cue.index,
            start_ms=scaled(cue.start_ms),
            end_ms=scaled(cue.end_ms),
            settings=cue.settings,
            text_lines=cue.text_lines,
        )
        for cue in cues
    ]
    validate_cues(result, "retimed output")
    return result


def render_srt(cues: list[Cue]) -> str:
    blocks = []
    for cue in cues:
        timing = (
            f"{ms_to_timestamp(cue.start_ms)} --> {ms_to_timestamp(cue.end_ms)}"
            f"{cue.settings}"
        )
        blocks.append("\n".join((str(cue.index), timing, *cue.text_lines)))
    return "\n\n".join(blocks) + "\n"


def parse_speed(value: str) -> Decimal:
    try:
        speed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("speed must be a decimal number") from exc
    if not speed.is_finite() or speed <= 0:
        raise argparse.ArgumentTypeError("speed must be finite and greater than zero")
    return speed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Shorten SRT timestamps by a constant playback speed while preserving all text."
    )
    parser.add_argument("input", type=Path, help="source SRT path")
    parser.add_argument("output", type=Path, help="destination SRT path; must differ from input")
    parser.add_argument("--speed", required=True, type=parse_speed, help="playback speed, e.g. 1.1")
    parser.add_argument("--force", action="store_true", help="replace an existing output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source = args.input.resolve()
    destination = args.output.resolve()
    if source == destination:
        print("error: input and output paths must differ", file=sys.stderr)
        return 2
    if not source.is_file():
        print(f"error: input SRT does not exist: {source}", file=sys.stderr)
        return 2
    if destination.exists() and not args.force:
        print(
            f"error: output already exists: {destination}; pass --force to replace it",
            file=sys.stderr,
        )
        return 2

    temporary: Path | None = None
    try:
        cues = parse_srt(source.read_text(encoding="utf-8-sig"))
        retimed = retime(cues, args.speed)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.stem}-",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(render_srt(retimed))
        temporary.replace(destination)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    print(
        json.dumps(
            {
                "ok": True,
                "input": str(source),
                "output": str(destination),
                "speed": str(args.speed),
                "cue_count": len(retimed),
                "input_end_ms": cues[-1].end_ms,
                "output_end_ms": retimed[-1].end_ms,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
