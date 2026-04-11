#!/usr/bin/env python3
"""Create a framed photo poster with EXIF metadata and dominant colors."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PIL import ExifTags, Image, ImageDraw, ImageFont, ImageOps


EXIF_TAGS = {v: k for k, v in ExifTags.TAGS.items()}
GPS_TAGS = {v: k for k, v in ExifTags.GPSTAGS.items()}


@dataclass
class LayoutConfig:
    frame_color: tuple[int, int, int]
    top_margin: int
    bottom_margin: int
    side_margin: int
    title: str
    subtitle: str | None
    title_size: int
    subtitle_size: int
    info_size: int
    meta_size: int
    font_path: str | None


def parse_hex_color(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise argparse.ArgumentTypeError("Color must be a 6-digit hex value, e.g. F2F2F2")
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Invalid hex color value") from exc


def load_font(font_path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path:
        return ImageFont.truetype(font_path, size=size)

    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)

    return ImageFont.load_default()


def _to_float_fraction(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, tuple) and len(value) == 2 and value[1] != 0:
        return float(value[0]) / float(value[1])
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_date(exif_dt: str | None) -> str | None:
    if not exif_dt:
        return None
    formats = ["%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"]
    for fmt in formats:
        try:
            dt = datetime.strptime(exif_dt.strip(), fmt)
            return dt.strftime("%b %d, %Y")
        except ValueError:
            continue
    return exif_dt


def _format_gps_coord(values: Iterable, ref: str | None, kind: str) -> str | None:
    try:
        d, m, s = list(values)[:3]
    except (TypeError, ValueError):
        return None

    deg = _to_float_fraction(d)
    minute = _to_float_fraction(m)
    sec = _to_float_fraction(s)
    coord = deg + minute / 60 + sec / 3600

    if ref:
        if ref.upper() in {"S", "W"}:
            coord *= -1
        suffix = ref.upper()
    else:
        suffix = ""

    if kind == "lat":
        default_suffix = "N" if coord >= 0 else "S"
    else:
        default_suffix = "E" if coord >= 0 else "W"

    return f"{abs(coord):.6f}°{suffix or default_suffix}"


def get_exif_data(image: Image.Image) -> dict:
    raw_exif = image.getexif()
    if not raw_exif:
        return {}

    parsed = {}
    for tag_id, value in raw_exif.items():
        tag_name = ExifTags.TAGS.get(tag_id, tag_id)
        if tag_name == "GPSInfo" and isinstance(value, dict):
            parsed[tag_name] = {ExifTags.GPSTAGS.get(k, k): v for k, v in value.items()}
        else:
            parsed[tag_name] = value
    return parsed


def dominant_colors(image: Image.Image, n_colors: int = 5) -> list[tuple[int, int, int]]:
    reduced = image.convert("RGB").resize((600, 600))
    palette_img = reduced.quantize(colors=max(n_colors, 5), method=Image.Quantize.MEDIANCUT)
    palette = palette_img.getpalette() or []
    color_counts = sorted(palette_img.getcolors() or [], reverse=True)

    colors = []
    for _, color_index in color_counts:
        base = color_index * 3
        colors.append((palette[base], palette[base + 1], palette[base + 2]))
        if len(colors) == n_colors:
            break

    if len(colors) < n_colors:
        colors.extend([(0, 0, 0)] * (n_colors - len(colors)))
    return colors


def draw_color_swatches(draw: ImageDraw.ImageDraw, colors: list[tuple[int, int, int]], x: int, y: int, width: int, height: int) -> None:
    swatch_w = width / len(colors)
    for idx, color in enumerate(colors):
        x0 = int(x + idx * swatch_w)
        x1 = int(x + (idx + 1) * swatch_w)
        draw.rectangle((x0, y, x1, y + height), fill=color)


def create_framed_image(input_path: Path, output_path: Path, cfg: LayoutConfig) -> None:
    source = Image.open(input_path)
    source = ImageOps.exif_transpose(source).convert("RGB")
    width, height = source.size

    canvas_w = width + cfg.side_margin * 2
    canvas_h = height + cfg.top_margin + cfg.bottom_margin

    canvas = Image.new("RGB", (canvas_w, canvas_h), cfg.frame_color)
    canvas.paste(source, (cfg.side_margin, cfg.top_margin))
    draw = ImageDraw.Draw(canvas)

    title_font = load_font(cfg.font_path, cfg.title_size)
    subtitle_font = load_font(cfg.font_path, cfg.subtitle_size)
    info_font = load_font(cfg.font_path, cfg.info_size)
    meta_font = load_font(cfg.font_path, cfg.meta_size)

    exif = get_exif_data(source)
    make = str(exif.get("Make", "")).strip()
    model = str(exif.get("Model", "")).strip()
    camera = f"{make} {model}".strip() or "Unknown Camera"

    date_value = _format_date(exif.get("DateTimeOriginal") or exif.get("DateTime"))
    subtitle = cfg.subtitle if cfg.subtitle else (f"PHOTOGRAPHED IN : {date_value}" if date_value else "")

    gps = exif.get("GPSInfo", {}) if isinstance(exif.get("GPSInfo"), dict) else {}
    lat = _format_gps_coord(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"), "lat") if gps else None
    lon = _format_gps_coord(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"), "lon") if gps else None
    gps_line = f"{lat} {lon}" if lat and lon else ""

    def exif_num(tag: str) -> float:
        return _to_float_fraction(exif.get(tag))

    focal_length = exif_num("FocalLength")
    f_number = exif_num("FNumber")
    exposure = exif.get("ExposureTime")
    iso = exif.get("ISOSpeedRatings") or exif.get("PhotographicSensitivity")

    exposure_text = ""
    if isinstance(exposure, tuple) and len(exposure) == 2 and exposure[1] != 0:
        exposure_text = f"{exposure[0]}/{exposure[1]}"
    elif exposure:
        exposure_text = str(exposure)

    spec_chunks = [
        f"{focal_length:.0f}mm" if focal_length else "--mm",
        f"f/{f_number:.1f}" if f_number else "f/--",
        exposure_text or "--",
        f"ISO{iso}" if iso else "ISO--",
    ]
    specs = "    ".join(spec_chunks)

    pad_x = cfg.side_margin
    top_y = max(18, int(cfg.top_margin * 0.2))
    draw.text((pad_x, top_y), cfg.title, fill=(20, 20, 20), font=title_font)

    if subtitle:
        subtitle_y = top_y + cfg.title_size + 8
        draw.text((pad_x, subtitle_y), subtitle, fill=(120, 120, 120), font=subtitle_font)

    bottom_inner_top = cfg.top_margin + height + max(12, cfg.bottom_margin // 10)
    swatch_height = max(24, cfg.bottom_margin // 6)
    swatch_width = min(width // 2, 520)

    colors = dominant_colors(source, n_colors=5)
    draw_color_swatches(draw, colors, pad_x, bottom_inner_top, swatch_width, swatch_height)

    right_x = canvas_w - cfg.side_margin
    camera_bbox = draw.textbbox((0, 0), camera, font=info_font)
    camera_w = camera_bbox[2] - camera_bbox[0]
    draw.text((right_x - camera_w, bottom_inner_top), camera, fill=(20, 20, 20), font=info_font)

    specs_y = bottom_inner_top + cfg.info_size + 12
    specs_bbox = draw.textbbox((0, 0), specs, font=meta_font)
    specs_w = specs_bbox[2] - specs_bbox[0]
    draw.text((right_x - specs_w, specs_y), specs, fill=(120, 120, 120), font=meta_font)

    if gps_line:
        gps_y = specs_y + cfg.meta_size + 8
        gps_bbox = draw.textbbox((0, 0), gps_line, font=meta_font)
        gps_w = gps_bbox[2] - gps_bbox[0]
        draw.text((right_x - gps_w, gps_y), gps_line, fill=(120, 120, 120), font=meta_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=95)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a framed JPG with EXIF summary and dominant colors")
    parser.add_argument("input", type=Path, help="Input JPEG file")
    parser.add_argument("output", type=Path, help="Output image path")
    parser.add_argument("--title", default="Nature's poetry", help="Display title on top")
    parser.add_argument("--subtitle", default=None, help="Override subtitle text under title")
    parser.add_argument("--frame-color", type=parse_hex_color, default="F2F2F2", help="Frame color hex (RRGGBB)")
    parser.add_argument("--top-margin", type=int, default=170, help="Top frame margin in pixels")
    parser.add_argument("--bottom-margin", type=int, default=190, help="Bottom frame margin in pixels")
    parser.add_argument("--side-margin", type=int, default=40, help="Left/right frame margin in pixels")
    parser.add_argument("--title-size", type=int, default=62, help="Title font size")
    parser.add_argument("--subtitle-size", type=int, default=42, help="Subtitle font size")
    parser.add_argument("--info-size", type=int, default=64, help="Camera model font size")
    parser.add_argument("--meta-size", type=int, default=38, help="Metadata font size")
    parser.add_argument("--font", dest="font_path", default=None, help="Path to TTF/OTF font")

    args = parser.parse_args()
    if args.top_margin < 0 or args.bottom_margin < 0 or args.side_margin < 0:
        parser.error("Margins must be non-negative")
    return args


def main() -> None:
    args = parse_args()
    if args.input.suffix.lower() not in {".jpg", ".jpeg"}:
        raise SystemExit("Input must be a JPG/JPEG file")

    cfg = LayoutConfig(
        frame_color=args.frame_color,
        top_margin=args.top_margin,
        bottom_margin=args.bottom_margin,
        side_margin=args.side_margin,
        title=args.title,
        subtitle=args.subtitle,
        title_size=args.title_size,
        subtitle_size=args.subtitle_size,
        info_size=args.info_size,
        meta_size=args.meta_size,
        font_path=args.font_path,
    )
    create_framed_image(args.input, args.output, cfg)
    print(f"Saved framed image to: {args.output}")


if __name__ == "__main__":
    main()
