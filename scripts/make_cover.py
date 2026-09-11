from __future__ import annotations

import argparse
import io
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFont
except ModuleNotFoundError as error:
    if error.name != "PIL":
        raise
    Image = ImageColor = ImageDraw = ImageEnhance = ImageFont = None
    PIL_IMPORT_ERROR: ModuleNotFoundError | None = error
else:
    PIL_IMPORT_ERROR = None


REFERENCE_SIZE = (1080, 1920)
WHITE = "#FFFFFF"
YELLOW = "#FFD84D"
MINT = "#43E6C1"


@dataclass(frozen=True)
class Emphasis:
    text: str
    color: str


def extract_frame(video: Path, timestamp: float) -> Image.Image:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not available on PATH")

    command = [
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(video),
        "-ss",
        f"{timestamp:.3f}",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "pipe:1",
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as error:
        details = error.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg could not extract the frame: {details}") from error
    if not result.stdout:
        raise RuntimeError("ffmpeg returned no image data; check --time and --input")
    return Image.open(io.BytesIO(result.stdout)).convert("RGB")


def cover_crop(frame: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(width / frame.width, height / frame.height)
    resized = frame.resize(
        (round(frame.width * scale), round(frame.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def add_top_gradient(image: Image.Image) -> Image.Image:
    width, height = image.size
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    fade_end = min(height, round(height * 0.383))
    for y in range(fade_end):
        ratio = 1 - y / fade_end
        alpha = round(156 * ratio**0.72)
        draw.line((0, y, width, y), fill=(5, 8, 10, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def parse_emphasis_specs(
    parser: argparse.ArgumentParser,
    specs: list[str],
    lines: list[str],
) -> dict[int, Emphasis]:
    parsed: dict[int, Emphasis] = {}
    for spec in specs:
        parts = spec.split(":", 2)
        if len(parts) not in (2, 3):
            parser.error(
                f"invalid --emphasis {spec!r}; use LINE:TEXT or LINE:TEXT:COLOR"
            )
        try:
            line_number = int(parts[0])
        except ValueError:
            parser.error(f"invalid line number in --emphasis {spec!r}")
        if line_number < 1 or line_number > len(lines):
            parser.error(f"--emphasis line must be between 1 and {len(lines)}")
        if line_number in parsed:
            parser.error(f"line {line_number} has more than one --emphasis")

        text = parts[1]
        color = parts[2] if len(parts) == 3 else YELLOW
        if not text or text not in lines[line_number - 1]:
            parser.error(
                f"emphasis text {text!r} is not present in line {line_number}"
            )
        try:
            ImageColor.getrgb(color)
        except ValueError:
            parser.error(f"invalid emphasis color {color!r}")
        parsed[line_number] = Emphasis(text=text, color=color)
    return parsed


def line_runs(line: str, emphasis: Emphasis | None) -> list[tuple[str, str]]:
    if not emphasis:
        return [(line, WHITE)]
    before, match, after = line.partition(emphasis.text)
    return [
        (text, color)
        for text, color in (
            (before, WHITE),
            (match, emphasis.color),
            (after, WHITE),
        )
        if text
    ]


def fit_font(
    font_path: Path,
    text: str,
    target_size: int,
    minimum_size: int,
    max_width: int,
) -> ImageFont.FreeTypeFont:
    size = target_size
    while size >= minimum_size:
        font = ImageFont.truetype(str(font_path), size)
        if font.getlength(text) <= max_width:
            return font
        size -= 2
    raise ValueError(f"title line is too long to fit safely: {text!r}")


def draw_runs(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    runs: list[tuple[str, str]],
    font: ImageFont.FreeTypeFont,
    unit: float,
) -> None:
    stroke = max(2, round(7 * unit))
    shadow_stroke = max(stroke + 1, round(11 * unit))
    shadow_offset = max(2, round(8 * unit))

    x, y = xy
    for text, _ in runs:
        draw.text(
            (x, y + shadow_offset),
            text,
            font=font,
            fill=(0, 0, 0, 220),
            stroke_width=shadow_stroke,
            stroke_fill=(0, 0, 0, 205),
            anchor="lt",
        )
        x += round(draw.textlength(text, font=font))

    x, y = xy
    for text, color in runs:
        draw.text(
            (x, y),
            text,
            font=font,
            fill=color,
            stroke_width=stroke,
            stroke_fill="#090B0D",
            anchor="lt",
        )
        x += round(draw.textlength(text, font=font))


def compose_cover(
    frame: Image.Image,
    width: int,
    height: int,
    label: str,
    lines: list[str],
    emphasis: dict[int, Emphasis],
    font_dir: Path,
) -> Image.Image:
    image = cover_crop(frame, width, height)
    image = ImageEnhance.Contrast(image).enhance(1.07)
    image = ImageEnhance.Color(image).enhance(1.04)
    image = ImageEnhance.Brightness(image).enhance(1.015)
    image = ImageEnhance.Sharpness(image).enhance(1.08)
    image = add_top_gradient(image)

    bold = font_dir / "NotoSansSC-Bold.otf"
    if not bold.exists():
        raise FileNotFoundError(f"font asset is missing: {bold}")

    sx = width / REFERENCE_SIZE[0]
    sy = height / REFERENCE_SIZE[1]
    unit = min(sx, sy)
    x = round(74 * sx)
    max_text_width = width - x - round(72 * sx)
    minimum_size = max(24, round(58 * unit))
    if len(lines) == 2:
        font_sizes = [round(142 * unit), round(170 * unit)]
        positions = (244, 414) if label else (186, 356)
        line_y = [round(value * sy) for value in positions]
    else:
        font_sizes = [round(114 * unit), round(114 * unit), round(152 * unit)]
        line_y = [round(value * sy) for value in (244, 365, 486)]

    draw = ImageDraw.Draw(image)
    if label:
        label_font = fit_font(
            bold,
            label,
            round(42 * unit),
            max(20, round(28 * unit)),
            max_text_width - round(82 * sx),
        )
        label_x, label_y = x, round(142 * sy)
        label_height = round(72 * sy)
        label_width = round(draw.textlength(label, font=label_font)) + round(82 * sx)
        draw.rounded_rectangle(
            (label_x, label_y, label_x + label_width, label_y + label_height),
            radius=max(2, round(8 * unit)),
            fill=(7, 13, 15, 218),
            outline=(67, 230, 193, 180),
            width=max(1, round(2 * unit)),
        )
        draw.rounded_rectangle(
            (
                label_x + round(18 * sx),
                label_y + round(14 * sy),
                label_x + round(26 * sx),
                label_y + round(58 * sy),
            ),
            radius=max(1, round(4 * unit)),
            fill=MINT,
        )
        draw.text(
            (label_x + round(44 * sx), label_y + round(11 * sy)),
            label,
            font=label_font,
            fill=WHITE,
            anchor="lt",
        )

    for index, line in enumerate(lines):
        font = fit_font(
            bold,
            line,
            font_sizes[index],
            minimum_size,
            max_text_width,
        )
        draw_runs(
            draw,
            (x, line_y[index]),
            line_runs(line, emphasis.get(index + 1)),
            font,
            unit,
        )

    return image.convert("RGB")


def save_image(image: Image.Image, output: Path) -> None:
    suffix = output.suffix.lower()
    if suffix not in (".jpg", ".jpeg"):
        raise ValueError("--output must end in .jpg or .jpeg")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{output.stem}-",
        suffix=".tmp",
        dir=output.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        image.save(temporary, "JPEG", quality=94, subsampling=0, optimize=True)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    skill_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Extract a clean video frame and build a Kaipai-style vertical cover."
    )
    parser.add_argument("--input", type=Path, required=True, help="source video")
    parser.add_argument("--output", type=Path, required=True, help="JPG output")
    parser.add_argument("--time", type=float, default=0.0, help="source time in seconds")
    parser.add_argument("--label", default="", help="optional small top label")
    parser.add_argument(
        "--line",
        action="append",
        required=True,
        help="title line; repeat two or three times",
    )
    parser.add_argument(
        "--emphasis",
        action="append",
        default=[],
        metavar="LINE:TEXT[:COLOR]",
        help="highlight text in one line, for example 2:AI:#43E6C1",
    )
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--force", action="store_true", help="replace an existing output")
    parser.add_argument(
        "--font-dir",
        type=Path,
        default=skill_dir / "assets" / "fonts",
        help=argparse.SUPPRESS,
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if PIL_IMPORT_ERROR is not None:
        parser.exit(
            2,
            "error: Pillow is required; install it with "
            "`python -m pip install Pillow`.\n",
        )
    if len(args.line) not in (2, 3):
        parser.error("repeat --line two or three times")
    if not math.isfinite(args.time) or args.time < 0:
        parser.error("--time must be finite and non-negative")
    if args.width <= 0 or args.height <= 0:
        parser.error("--width and --height must be positive")
    if not all(line.strip() for line in args.line):
        parser.error("--line values must not be empty")

    source = args.input.resolve()
    output = args.output.resolve()
    if not source.is_file():
        parser.error(f"input video does not exist: {source}")
    if output.suffix.lower() not in (".jpg", ".jpeg"):
        parser.error("--output must end in .jpg or .jpeg")
    if output.exists() and not args.force:
        parser.error(f"output already exists: {output}; pass --force to replace it")

    emphasis = parse_emphasis_specs(parser, args.emphasis, args.line)
    try:
        frame = extract_frame(source, args.time)
        cover = compose_cover(
            frame=frame,
            width=args.width,
            height=args.height,
            label=args.label,
            lines=args.line,
            emphasis=emphasis,
            font_dir=args.font_dir.resolve(),
        )
        save_image(cover, output)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    print(f"Wrote {output} ({cover.width}x{cover.height})")


if __name__ == "__main__":
    main()
