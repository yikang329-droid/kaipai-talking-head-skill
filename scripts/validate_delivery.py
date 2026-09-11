#!/usr/bin/env python3
"""Validate a vertical MP4 delivery and its optional cover and SRT files."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any


TIMING_RE = re.compile(
    r"^(?P<start>\d{2,}):(?P<start_min>[0-5]\d):(?P<start_sec>[0-5]\d),(?P<start_ms>\d{3})"
    r"\s+-->\s+"
    r"(?P<end>\d{2,}):(?P<end_min>[0-5]\d):(?P<end_sec>[0-5]\d),(?P<end_ms>\d{3})"
    r"(?:\s+.*)?$"
)
INTEGRATED_RE = re.compile(
    r"Integrated loudness:\s+I:\s*(?P<value>[-+]?(?:inf|\d+(?:\.\d+)?))\s+LUFS",
    re.IGNORECASE,
)
TRUE_PEAK_RE = re.compile(
    r"True peak:\s+Peak:\s*(?P<value>[-+]?(?:inf|\d+(?:\.\d+)?))\s+dBFS",
    re.IGNORECASE,
)
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")


class ToolError(RuntimeError):
    pass


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def probe(path: Path, ffprobe: str) -> dict[str, Any]:
    completed = run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            "--",
            str(path),
        ]
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "ffprobe returned no diagnostic"
        raise ToolError(f"ffprobe failed for {path}: {detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ToolError(f"ffprobe returned invalid JSON for {path}: {exc}") from exc


def decode(path: Path, ffmpeg: str, image: bool = False) -> tuple[bool, str]:
    command = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-xerror", "-i", str(path)]
    if image:
        command.extend(["-frames:v", "1"])
    else:
        command.extend(["-map", "0:v", "-map", "0:a?"])
    command.extend(["-f", "null", "-"])
    completed = run(command)
    return completed.returncode == 0, completed.stderr.strip()


def measure_loudness(path: Path, ffmpeg: str) -> dict[str, float | str]:
    completed = run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-nostats",
            "-v",
            "info",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-af",
            "ebur128=peak=true:framelog=verbose",
            "-f",
            "null",
            "-",
        ]
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "ffmpeg returned no diagnostic"
        raise ToolError(f"EBU R128 measurement failed for {path}: {detail}")
    integrated_matches = INTEGRATED_RE.findall(completed.stderr)
    peak_matches = TRUE_PEAK_RE.findall(completed.stderr)
    if not integrated_matches or not peak_matches:
        raise ToolError("ffmpeg EBU R128 output did not contain a final loudness summary")

    integrated = float(integrated_matches[-1])
    true_peak = float(peak_matches[-1])
    return {
        "integrated_lufs": integrated if math.isfinite(integrated) else str(integrated),
        "true_peak_dbtp": true_peak if math.isfinite(true_peak) else str(true_peak),
    }


def timestamp_ms(hours: str, minutes: str, seconds: str, milliseconds: str) -> int:
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        + int(milliseconds)
    )


def inspect_srt(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ToolError(f"cannot read SRT {path}: {exc}") from exc
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not normalized:
        raise ToolError(f"SRT is empty: {path}")

    previous_start = -1
    previous_end = -1
    last_end = 0
    cue_count = 0
    errors: list[str] = []
    for block_number, block in enumerate(
        re.split(r"\n[ \t]*\n+", normalized), start=1
    ):
        lines = block.split("\n")
        if len(lines) < 3:
            errors.append(f"block {block_number} must contain index, timing, and text")
            continue
        try:
            cue_index = int(lines[0].strip())
        except ValueError:
            cue_index = None
            errors.append(f"block {block_number} has a non-numeric cue index")
        if cue_index is not None and cue_index != block_number:
            errors.append(
                f"block {block_number} must use sequential cue index {block_number}, "
                f"got {cue_index}"
            )
        subtitle_lines = [line.strip() for line in lines[2:] if line.strip()]
        if not subtitle_lines:
            errors.append(f"cue {cue_index or block_number} has no subtitle text")
        else:
            if not CJK_RE.search(subtitle_lines[0]):
                errors.append(f"cue {cue_index or block_number} must put Chinese on the first text line")
            if len(subtitle_lines) < 2 or not any(
                LATIN_RE.search(line) for line in subtitle_lines[1:]
            ):
                errors.append(f"cue {cue_index or block_number} must put English below Chinese")
        match = TIMING_RE.fullmatch(lines[1].strip())
        if not match:
            errors.append(f"block {block_number} has an invalid timing line")
            continue
        start = timestamp_ms(
            match.group("start"),
            match.group("start_min"),
            match.group("start_sec"),
            match.group("start_ms"),
        )
        end = timestamp_ms(
            match.group("end"),
            match.group("end_min"),
            match.group("end_sec"),
            match.group("end_ms"),
        )
        cue_count += 1
        if start >= end:
            errors.append(f"cue {lines[0].strip()} does not satisfy start < end")
        if start <= previous_start or end <= previous_end:
            errors.append(f"cue {lines[0].strip()} is not strictly increasing")
        if previous_end >= 0 and start < previous_end:
            errors.append(f"cue {lines[0].strip()} overlaps the previous cue")
        previous_start = start
        previous_end = end
        last_end = max(last_end, end)

    return {"cue_count": cue_count, "last_end_ms": last_end, "errors": errors}


def rate_value(raw_value: Any) -> tuple[str, float | None]:
    raw = str(raw_value or "0/0")
    try:
        fraction = Fraction(raw)
    except (ValueError, ZeroDivisionError):
        return raw, None
    return raw, float(fraction) if fraction.denominator and fraction.numerator else None


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def stream_end(stream: dict[str, Any]) -> float | None:
    duration = number(stream.get("duration"))
    if duration is None:
        return None
    return (number(stream.get("start_time")) or 0.0) + duration


def stream_start(stream: dict[str, Any]) -> float | None:
    return number(stream.get("start_time"))


def add_check(
    result: dict[str, Any],
    name: str,
    ok: bool,
    expected: Any,
    actual: Any,
    detail: str | None = None,
) -> None:
    check = {"name": name, "ok": ok, "expected": expected, "actual": actual}
    if detail:
        check["detail"] = detail
    result["checks"].append(check)
    if not ok:
        message = f"{name}: expected {expected!r}, got {actual!r}"
        result["errors"].append(f"{message} ({detail})" if detail else message)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an MP4 by probing metadata and fully decoding it. Exit 0 passes, "
            "1 means validation failed, and 2 means a tool or input error."
        )
    )
    parser.add_argument("video", type=Path, help="MP4 delivery")
    parser.add_argument("--cover", type=Path, required=True, help="required JPG cover")
    parser.add_argument(
        "--srt",
        type=Path,
        required=True,
        help="required bilingual SRT whose last cue must fit the video",
    )
    parser.add_argument(
        "--edited-duration",
        type=float,
        required=True,
        metavar="SECONDS",
        help="retained timeline duration before playback-rate adjustment",
    )
    parser.add_argument("--playback-rate", type=float, default=1.1)
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--fps-tolerance", type=float, default=0.001)
    parser.add_argument("--video-codec", default="h264")
    parser.add_argument("--video-profile", default="High")
    parser.add_argument("--pixel-format", default="yuv420p")
    parser.add_argument("--audio-codec", default="aac")
    parser.add_argument("--audio-profile", default="LC")
    parser.add_argument("--audio-rate", type=int, default=48000)
    parser.add_argument(
        "--audio-channels",
        type=int,
        choices=(1, 2),
        help="require an exact channel count; the default accepts mono or stereo",
    )
    parser.add_argument("--av-tail-frames", type=float, default=1.0)
    parser.add_argument("--frames", type=int, help="optional exact video frame count")
    parser.add_argument(
        "--srt-tolerance-ms",
        type=int,
        help="allowed subtitle overrun in milliseconds; the default is one video frame",
    )
    parser.add_argument("--loudness-target", type=float, default=-14.0, metavar="LUFS")
    parser.add_argument("--loudness-tolerance", type=float, default=0.6, metavar="LU")
    parser.add_argument("--true-peak-max", type=float, default=-1.0, metavar="DBTP")
    parser.add_argument("--cover-codec", default="mjpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.width <= 0 or args.height <= 0:
        parser.error("--width and --height must be positive")
    if args.fps <= 0:
        parser.error("--fps must be positive")
    if not math.isfinite(args.edited_duration) or args.edited_duration <= 0:
        parser.error("--edited-duration must be finite and positive")
    if not math.isfinite(args.playback_rate) or args.playback_rate <= 0:
        parser.error("--playback-rate must be finite and positive")
    if args.srt_tolerance_ms is not None and args.srt_tolerance_ms < 0:
        parser.error("--srt-tolerance-ms must be non-negative")
    if args.av_tail_frames < 0:
        parser.error("--av-tail-frames must be non-negative")
    result: dict[str, Any] = {
        "ok": False,
        "exit_code": None,
        "video": str(args.video.resolve()),
        "cover": str(args.cover.resolve()) if args.cover else None,
        "srt": str(args.srt.resolve()) if args.srt else None,
        "checks": [],
        "errors": [],
    }

    try:
        ffprobe = shutil.which(args.ffprobe)
        ffmpeg = shutil.which(args.ffmpeg)
        if not ffprobe or not ffmpeg:
            missing = [name for name, path in ((args.ffprobe, ffprobe), (args.ffmpeg, ffmpeg)) if not path]
            raise ToolError(f"required executable not found: {', '.join(missing)}")
        if not args.video.is_file():
            raise ToolError(f"video does not exist: {args.video}")
        if args.cover and not args.cover.is_file():
            raise ToolError(f"cover does not exist: {args.cover}")
        if args.srt and not args.srt.is_file():
            raise ToolError(f"SRT does not exist: {args.srt}")

        metadata = probe(args.video, ffprobe)
        streams = metadata.get("streams", [])
        video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        format_name = metadata.get("format", {}).get("format_name", "")
        duration = number(metadata.get("format", {}).get("duration")) or 0.0
        result["media"] = {
            "format_name": format_name,
            "duration_seconds": duration,
            "stream_count": len(streams),
        }
        add_check(result, "mp4_container", args.video.suffix.lower() == ".mp4" and "mp4" in format_name, "MP4", format_name)
        add_check(result, "has_video", bool(video_streams), True, bool(video_streams))
        add_check(result, "has_audio", bool(audio_streams), True, bool(audio_streams))

        actual_fps: float | None = None
        if video_streams:
            video = video_streams[0]
            raw_avg_fps, actual_fps = rate_value(video.get("avg_frame_rate"))
            raw_r_fps, actual_r_fps = rate_value(video.get("r_frame_rate"))
            frame_count = (
                int(video["nb_frames"])
                if str(video.get("nb_frames", "")).isdigit()
                else None
            )
            video_duration = number(video.get("duration"))
            result["media"]["video"] = {
                "codec": video.get("codec_name"),
                "profile": video.get("profile"),
                "pixel_format": video.get("pix_fmt"),
                "sample_aspect_ratio": video.get("sample_aspect_ratio"),
                "field_order": video.get("field_order"),
                "width": video.get("width"),
                "height": video.get("height"),
                "avg_frame_rate": raw_avg_fps,
                "r_frame_rate": raw_r_fps,
                "frames": frame_count,
                "duration_seconds": video_duration,
            }
            add_check(result, "video_width", video.get("width") == args.width, args.width, video.get("width"))
            add_check(result, "video_height", video.get("height") == args.height, args.height, video.get("height"))
            add_check(result, "video_codec", video.get("codec_name") == args.video_codec, args.video_codec, video.get("codec_name"))
            add_check(result, "video_profile", video.get("profile") == args.video_profile, args.video_profile, video.get("profile"))
            add_check(result, "pixel_format", video.get("pix_fmt") == args.pixel_format, args.pixel_format, video.get("pix_fmt"))
            add_check(result, "square_pixels", video.get("sample_aspect_ratio") == "1:1", "1:1", video.get("sample_aspect_ratio"))
            field_order = video.get("field_order")
            add_check(
                result,
                "progressive_scan",
                field_order == "progressive",
                "progressive",
                field_order or "not reported",
            )
            add_check(
                result,
                "average_frame_rate",
                actual_fps is not None and abs(actual_fps - args.fps) <= args.fps_tolerance,
                args.fps,
                actual_fps,
                f"reported as {raw_avg_fps}",
            )
            add_check(
                result,
                "real_frame_rate",
                actual_r_fps is not None
                and abs(actual_r_fps - args.fps) <= args.fps_tolerance,
                args.fps,
                actual_r_fps,
                f"reported as {raw_r_fps}",
            )
            if args.frames is not None:
                add_check(result, "video_frames", frame_count == args.frames, args.frames, frame_count)
            expected_frames = (
                round(video_duration * args.fps)
                if video_duration is not None
                else None
            )
            add_check(
                result,
                "constant_frame_count",
                frame_count is not None and frame_count == expected_frames,
                expected_frames,
                frame_count,
            )

            expected_duration = args.edited_duration / args.playback_rate
            duration_tolerance = 1 / actual_fps if actual_fps else None
            duration_delta = abs(duration - expected_duration)
            result["timing"] = {
                "edited_duration_seconds": args.edited_duration,
                "playback_rate": args.playback_rate,
                "expected_output_duration_seconds": expected_duration,
                "actual_output_duration_seconds": duration,
                "difference_ms": round(duration_delta * 1000, 3),
            }
            add_check(
                result,
                "playback_rate_duration",
                duration_tolerance is not None
                and duration_delta <= duration_tolerance + 1e-9,
                f"{expected_duration:.6f}s +/- 1 frame",
                f"{duration:.6f}s",
                f"difference {duration_delta * 1000:.3f} ms",
            )

        if audio_streams:
            audio = audio_streams[0]
            sample_rate = int(audio.get("sample_rate", 0) or 0)
            result["media"]["audio"] = {
                "codec": audio.get("codec_name"),
                "profile": audio.get("profile"),
                "sample_rate": sample_rate,
                "channels": audio.get("channels"),
                "duration_seconds": number(audio.get("duration")),
            }
            add_check(result, "audio_codec", audio.get("codec_name") == args.audio_codec, args.audio_codec, audio.get("codec_name"))
            add_check(result, "audio_profile", audio.get("profile") == args.audio_profile, args.audio_profile, audio.get("profile"))
            add_check(result, "audio_sample_rate", sample_rate == args.audio_rate, args.audio_rate, sample_rate)
            actual_channels = audio.get("channels")
            expected_channels: int | str = (
                args.audio_channels if args.audio_channels is not None else "mono or stereo"
            )
            channel_ok = (
                actual_channels == args.audio_channels
                if args.audio_channels is not None
                else actual_channels in {1, 2}
            )
            add_check(result, "audio_channels", channel_ok, expected_channels, actual_channels)

        if video_streams and audio_streams:
            video_start = stream_start(video_streams[0])
            audio_start = stream_start(audio_streams[0])
            video_end = stream_end(video_streams[0])
            audio_end = stream_end(audio_streams[0])
            allowed_delta = args.av_tail_frames / actual_fps if actual_fps else None
            start_delta = (
                abs(video_start - audio_start)
                if video_start is not None and audio_start is not None
                else None
            )
            actual_delta = (
                abs(video_end - audio_end)
                if video_end is not None and audio_end is not None
                else None
            )
            result["media"]["av_end_delta_ms"] = (
                round(actual_delta * 1000, 3) if actual_delta is not None else None
            )
            result["media"]["av_start_delta_ms"] = (
                round(start_delta * 1000, 3) if start_delta is not None else None
            )
            add_check(
                result,
                "av_start_delta",
                start_delta is not None
                and allowed_delta is not None
                and start_delta <= allowed_delta + 1e-9,
                f"<= {args.av_tail_frames:g} frame ({allowed_delta * 1000:.3f} ms)"
                if allowed_delta is not None
                else f"<= {args.av_tail_frames:g} frame",
                f"{start_delta * 1000:.3f} ms" if start_delta is not None else "unavailable",
            )
            add_check(
                result,
                "av_end_delta",
                actual_delta is not None
                and allowed_delta is not None
                and actual_delta <= allowed_delta + 1e-9,
                f"<= {args.av_tail_frames:g} frame ({allowed_delta * 1000:.3f} ms)"
                if allowed_delta is not None
                else f"<= {args.av_tail_frames:g} frame",
                f"{actual_delta * 1000:.3f} ms" if actual_delta is not None else "unavailable",
            )

        decoded, decode_error = decode(args.video, ffmpeg)
        add_check(result, "full_decode", decoded, True, decoded, decode_error or None)

        if audio_streams:
            loudness = measure_loudness(args.video, ffmpeg)
            result["loudness"] = {"checked": True, **loudness}
            integrated = loudness["integrated_lufs"]
            true_peak = loudness["true_peak_dbtp"]
            add_check(
                result,
                "integrated_loudness",
                isinstance(integrated, float)
                and abs(integrated - args.loudness_target) <= args.loudness_tolerance,
                f"{args.loudness_target:g} ± {args.loudness_tolerance:g} LUFS",
                integrated,
            )
            add_check(
                result,
                "true_peak",
                isinstance(true_peak, float) and true_peak <= args.true_peak_max,
                f"<= {args.true_peak_max:g} dBTP",
                true_peak,
            )

        if args.cover:
            cover_metadata = probe(args.cover, ffprobe)
            cover_stream = next(
                (stream for stream in cover_metadata.get("streams", []) if stream.get("codec_type") == "video"),
                None,
            )
            cover_decoded, cover_decode_error = decode(args.cover, ffmpeg, image=True)
            result["cover_media"] = {
                "codec": cover_stream.get("codec_name") if cover_stream else None,
                "width": cover_stream.get("width") if cover_stream else None,
                "height": cover_stream.get("height") if cover_stream else None,
            }
            add_check(result, "cover_is_jpg", args.cover.suffix.lower() in {".jpg", ".jpeg"}, "JPG", args.cover.suffix.lower())
            add_check(result, "cover_codec", bool(cover_stream) and cover_stream.get("codec_name") == args.cover_codec, args.cover_codec, cover_stream.get("codec_name") if cover_stream else None)
            add_check(result, "cover_width", bool(cover_stream) and cover_stream.get("width") == args.width, args.width, cover_stream.get("width") if cover_stream else None)
            add_check(result, "cover_height", bool(cover_stream) and cover_stream.get("height") == args.height, args.height, cover_stream.get("height") if cover_stream else None)
            add_check(result, "cover_decode", cover_decoded, True, cover_decoded, cover_decode_error or None)

        if args.srt:
            srt = inspect_srt(args.srt)
            result["subtitle"] = srt
            add_check(result, "srt_structure", not srt["errors"], "valid increasing non-overlapping cues", srt["errors"] or "valid")
            video_end_ms = round(duration * 1000)
            fps_for_tolerance = actual_fps or args.fps
            srt_tolerance_ms = (
                args.srt_tolerance_ms
                if args.srt_tolerance_ms is not None
                else math.ceil(1000 / fps_for_tolerance)
            )
            add_check(
                result,
                "srt_within_video",
                srt["last_end_ms"] <= video_end_ms + srt_tolerance_ms,
                f"<= {video_end_ms + srt_tolerance_ms} ms",
                srt["last_end_ms"],
                f"tolerance {srt_tolerance_ms} ms",
            )

    except ToolError as exc:
        result["errors"].append(str(exc))
        result["exit_code"] = 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    result["ok"] = not result["errors"]
    result["exit_code"] = 0 if result["ok"] else 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
