import logging
import math
import re
import struct
import subprocess
import textwrap
import zlib
from pathlib import Path

from .config import CLIP_DIR, WORK_DIR
from .media import MediaError, executable, probe, _ass_escape, _ass_time


_FONTS = {"Arial", "Georgia", "Segoe UI", "Tahoma", "Trebuchet MS", "Times New Roman"}
def _rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _write_gradient(path, width, height, start, end):
    top, bottom = _rgb(start), _rgb(end)
    with path.open("wb") as output:
        output.write(f"P6\n{width} {height}\n255\n".encode())
        for y in range(height):
            ratio = y / max(1, height - 1)
            color = bytes(round(top[index] + (bottom[index] - top[index]) * ratio) for index in range(3))
            output.write(color * width)


def _wrap_quote(text, box_width, font_size):
    columns = max(1, int(box_width / (font_size * 0.56)))
    lines = []
    for paragraph in text.replace("\r", "").split("\n"):
        lines.extend(textwrap.wrap(paragraph, width=columns, break_long_words=False, break_on_hyphens=False) or [""])
    return lines


def _quote_layout(text, composition, width, height):
    settings = composition["text"]
    requested_size = round(settings["font_size"] * width / 720)
    center_x = round(width * settings["x"] / 100)
    center_y = round(height * settings["y"] / 100)
    box_width = round(min(width * 0.82, center_x * 2, (width - center_x) * 2))
    minimum_size = max(round(20 * width / 720), round(requested_size * 0.72))
    font_size = requested_size
    while font_size >= minimum_size:
        lines = _wrap_quote(text, box_width, font_size)
        line_height = round(font_size * settings["line_spacing"])
        block_height = line_height * len(lines)
        top = center_y - block_height / 2
        safe_margin = round(height * 0.05)
        widest_line = max((len(line) for line in lines), default=0)
        if len(lines) <= 14 and box_width >= font_size and widest_line <= max(1, int(box_width / (font_size * 0.56))) and top >= safe_margin and top + block_height <= height - safe_margin:
            return lines, font_size, line_height, box_width, center_x, center_y
        font_size -= max(1, round(requested_size * 0.035))
    raise ValueError("Teks segmen tidak muat dalam safe margin. Pecah menjadi segmen lebih pendek, kurangi ukuran font sedikit, atau ubah posisi.")


def validate_quote_layout(text, composition, width=720, height=1280):
    _quote_layout(text, composition, width, height)


def _ass_color(color, opacity):
    red, green, blue = _rgb(color)
    alpha = round(255 * (100 - opacity) / 100)
    return f"&H{alpha:02X}{blue:02X}{green:02X}{red:02X}"


def _resolved_text_color(composition):
    settings, background = composition["text"], composition["background"]
    if not settings.get("auto_contrast") or background.get("kind") not in {"solid", "gradient"}:
        return settings["color"]
    colors = [background["color"]]
    if background.get("kind") == "gradient":
        colors.append(background["color2"])
    channels = [sum(_rgb(color)[index] for color in colors) / len(colors) / 255 for index in range(3)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#18211c" if luminance > 0.52 else "#ffffff"


def _write_text_gradient(path, opacity, center_y):
    """Write a small transparent PNG overlay; FFmpeg scales/composites it at render time."""
    width, height = 180, 320
    center = max(0.0, min(1.0, center_y / 100))
    top, bottom = max(0.0, center - 0.34), min(1.0, center + 0.34)
    peak = round(255 * max(0, min(80, opacity)) / 100)
    compressor = zlib.compressobj(6)
    compressed = bytearray()
    for y in range(height):
        vertical = y / max(1, height - 1)
        row = bytearray([0])
        for x in range(width):
            horizontal = x / max(1, width - 1)
            edge_x = min(1.0, horizontal / 0.12, (1 - horizontal) / 0.12)
            edge_y = min(1.0, max(0.0, (vertical - top) / 0.12), max(0.0, (bottom - vertical) / 0.12))
            alpha = round(peak * max(0.0, min(1.0, edge_x, edge_y)))
            row.extend((0, 0, 0, alpha))
        compressed.extend(compressor.compress(bytes(row)))
    compressed.extend(compressor.flush())

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", bytes(compressed)) + chunk(b"IEND", b"")
    path.write_bytes(png)


def _write_gradient_overlay(path, top_color, bottom_color, opacity):
    """Write small RGBA linear overlay; FFmpeg scales it once in its render graph."""
    width, height = 180, 320
    top, bottom = _rgb(top_color), _rgb(bottom_color)
    peak = round(255 * max(0, min(60, opacity)) / 100)
    compressor = zlib.compressobj(6)
    compressed = bytearray()
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(round(top[index] + (bottom[index] - top[index]) * ratio) for index in range(3))
        row = bytearray([0])
        for _ in range(width):
            row.extend((*color, peak))
        compressed.extend(compressor.compress(bytes(row)))
    compressed.extend(compressor.flush())

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", bytes(compressed)) + chunk(b"IEND", b"")
    path.write_bytes(png)


def _background_filter_chain(composition, width, height, duration):
    """Build bounded crop, motion and color filters for one background input."""
    visual = composition.get("visual") or {}
    background = composition["background"]
    chain = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
        f"setsar=1,fps=30,trim=duration={duration:.3f},setpts=PTS-STARTPTS,"
        f"tpad=stop_mode=clone:stop_duration={duration:.3f},trim=duration={duration:.3f}"
    )
    motion = visual.get("motion", "none")
    if background.get("kind") in {"image", "video"} and motion != "none":
        intensity = {"subtle": 0.04, "normal": 0.08, "strong": 0.12}.get(visual.get("motion_intensity"), 0.04)
        frames = max(1, round(duration * 30))
        progress = f"min(on/{frames},1)"
        ease = f"(0.5-0.5*cos(PI*{progress}))"
        if motion == "slow_zoom_in":
            zoom, x, y = f"1+{intensity}*{ease}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
        elif motion == "slow_zoom_out":
            zoom, x, y = f"1+{intensity}*(1-{ease})", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
        else:
            zoom = f"1+{intensity}" if motion.startswith("pan_") else f"1+{intensity}*(0.35+0.65*{ease})"
            pan = ease
            if motion == "pan_left":
                x, y = f"(iw-iw/zoom)*{pan}", "(ih-ih/zoom)/2"
            elif motion == "pan_right":
                x, y = f"(iw-iw/zoom)*(1-{pan})", "(ih-ih/zoom)/2"
            elif motion == "pan_up":
                x, y = "(iw-iw/zoom)/2", f"(ih-ih/zoom)*{pan}"
            elif motion == "pan_down":
                x, y = "(iw-iw/zoom)/2", f"(ih-ih/zoom)*(1-{pan})"
            else:  # Ken Burns: diagonal pan plus slow zoom, bounded by overscan.
                x, y = f"(iw-iw/zoom)*{pan}", f"(ih-ih/zoom)*(1-{pan})"
        chain += f",zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={width}x{height}:fps=30,trim=duration={duration:.3f},setpts=PTS-STARTPTS"

    brightness = float(visual.get("brightness", 0))
    contrast = float(visual.get("contrast", 1))
    saturation = float(visual.get("saturation", 1))
    if brightness or contrast != 1 or saturation != 1:
        chain += f",eq=brightness={brightness:.3f}:contrast={contrast:.3f}:saturation={saturation:.3f}"
    temperature = float(visual.get("temperature", 0))
    if temperature:
        warm = temperature * 0.12
        cool = -warm
        chain += f",colorbalance=rs={warm:.3f}:gs={temperature * 0.015:.3f}:bs={cool:.3f}:rm={warm:.3f}:bm={cool:.3f}"
    vignette = float(visual.get("vignette", 0))
    if vignette:
        chain += f",vignette=angle={math.pi / 4 * vignette:.4f}"
    grain = int(visual.get("grain", 0))
    if grain:
        chain += f",noise=alls={grain}:allf=t"
    dark_overlay = float(visual.get("dark_overlay", 0))
    if dark_overlay:
        chain += f",drawbox=x=0:y=0:w=iw:h=ih:color=black@{dark_overlay:.3f}:t=fill"
    return chain


def _video_filter_graph(composition, ass_path, width, height, duration, *, gradient_index=None, text_gradient_index=None):
    filters = [f"[0:v]{_background_filter_chain(composition, width, height, duration)},format=yuv420p[vbase]"]
    current = "vbase"
    if gradient_index is not None:
        filters.append(f"[{gradient_index}:v]scale={width}:{height}:flags=bilinear,format=rgba[atmosphere]")
        filters.append(f"[{current}][atmosphere]overlay=shortest=1:format=auto[vafteratmosphere]")
        current = "vafteratmosphere"
    if text_gradient_index is not None:
        filters.append(f"[{text_gradient_index}:v]scale={width}:{height}:flags=bilinear,format=rgba[textshade]")
        filters.append(f"[{current}][textshade]overlay=shortest=1:format=auto[vaftertextshade]")
        current = "vaftertextshade"
    filters.append(f"[{current}]format=yuv420p,ass='{_ass_escape(ass_path)}'[vout]")
    return ";".join(filters)


def _audio_mean_volume(ffmpeg, path, start=0.0, duration=None):
    args = [ffmpeg, "-hide_banner", "-nostdin", "-v", "info"]
    if start > 0:
        args.extend(["-ss", f"{start:.3f}"])
    args.extend(["-i", str(path)])
    if duration is not None:
        args.extend(["-t", f"{duration:.3f}"])
    args.extend(["-vn", "-af", "volumedetect", "-f", "null", "-"])
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=90, check=True)
    except (OSError, subprocess.SubprocessError):
        raise MediaError("FFmpeg tidak dapat memeriksa sinyal audio. Periksa file musik dan coba render ulang.") from None
    match = re.search(r"mean_volume:\s*(-inf|[-+\d.]+)\s*dB", result.stderr, re.IGNORECASE)
    if not match:
        raise MediaError("FFmpeg tidak memberikan hasil pengukuran audio yang valid.")
    if match.group(1).lower() == "-inf":
        return float("-inf")
    try:
        return float(match.group(1))
    except ValueError:
        return float("-inf")


def _write_sequential_ass(path, composition, width, height):
    settings = composition["text"]
    font = settings["font"] if settings["font"] in _FONTS else "Arial"
    primary = _ass_color(_resolved_text_color(composition), settings["opacity"])
    outline = _ass_color("#000000", settings["opacity"])
    bold = -1 if settings.get("font_weight", 600) >= 600 else 0
    base_size = round(settings["font_size"] * width / 720)
    outline_size = max(1, round(base_size * 0.035)) if settings["outline"] else 0
    shadow_size = max(1, round(base_size * 0.045)) if settings["shadow"] else 0
    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Mood,{font},{base_size},{primary},&H000000FF,{outline},&H80000000,{bold},0,1,"
        f"{outline_size},{shadow_size},5,48,48,0,1\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    events = []
    alignment = {"left": 4, "center": 5, "right": 6}[settings["alignment"]]
    for segment in composition.get("segments", []):
        text = segment["text"].replace("\\", "／").replace("{", "｛").replace("}", "｝")
        lines, font_size, line_height, box_width, center_x, center_y = _quote_layout(text, composition, width, height)
        if settings["alignment"] == "left":
            center_x -= box_width // 2
        elif settings["alignment"] == "right":
            center_x += box_width // 2
        span = segment["end"] - segment["start"]
        animation_duration = min(segment["animation_duration"], span / 2)
        animation = segment["animation"]
        milliseconds = round(animation_duration * 1000)
        for index, line in enumerate(lines):
            y = round(center_y + (index - (len(lines) - 1) / 2) * line_height)
            tags = [f"\\an{alignment}", f"\\fs{font_size}"]
            if animation == "fade_in":
                tags.append(f"\\fad({milliseconds},0)")
            elif animation == "fade_out":
                tags.append(f"\\fad(0,{milliseconds})")
            elif animation in {"fade_up", "slide_up"}:
                offset = round(font_size * (0.65 if animation == "fade_up" else 1.1))
                tags.extend([f"\\fad({milliseconds},0)", f"\\move({center_x},{y + offset},{center_x},{y},0,{milliseconds})"])
            elif animation == "gentle_scale":
                tags.extend([f"\\fad({milliseconds},0)", f"\\fscx96\\fscy96\\t(0,{milliseconds},\\fscx100\\fscy100)"])
            if animation not in {"fade_up", "slide_up"}:
                tags.append(f"\\pos({center_x},{y})")
            safe_line = line.replace(",", "，")
            events.append(
                f"Dialogue: 0,{_ass_time(segment['start'])},{_ass_time(segment['end'])},Mood,,0,0,0,,{{{' '.join(tags)}}}{safe_line}\n"
            )
    path.write_text(header + "".join(events), encoding="utf-8-sig")


def _write_quote_ass(path, text, composition, width, height, segments=None):
    settings = composition["text"]
    if composition.get("text_mode") == "sequential":
        _write_sequential_ass(path, composition, width, height)
        return
    font = settings["font"] if settings["font"] in _FONTS else "Arial"
    lines, font_size, line_height, box_width, center_x, center_y = _quote_layout(text, composition, width, height)
    alignment = {"left": 4, "center": 5, "right": 6}[settings["alignment"]]
    if settings["alignment"] == "left":
        center_x -= box_width // 2
    elif settings["alignment"] == "right":
        center_x += box_width // 2
    primary = _ass_color(_resolved_text_color(composition), settings["opacity"])
    outline = _ass_color("#000000", settings["opacity"])
    bold = -1 if settings.get("font_weight", 600) >= 600 else 0
    outline_size = max(1, round(font_size * 0.035)) if settings["outline"] else 0
    shadow_size = max(1, round(font_size * 0.045)) if settings["shadow"] else 0
    style = (
        f"Style: Mood,{font},{font_size},{primary},&H000000FF,{outline},&H80000000,{bold},0,1,"
        f"{outline_size},{shadow_size},{alignment},48,48,0,1\n"
    )
    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        + style
        + "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    text = text.replace("\\", "／").replace("{", "｛").replace("}", "｝")
    fade_seconds = min(settings["animation_duration"], (settings["end"] - settings["start"]) / 2)
    fade_in = round(fade_seconds * 1000) if settings["animation_in"] == "fade" else 0
    fade_out = round(fade_seconds * 1000) if settings["animation_out"] == "fade" else 0
    events = []
    duration = settings["end"] - settings["start"]

    def line_tags(index, count):
        y = round(center_y + (index - (count - 1) / 2) * line_height)
        tags = [f"\\an{alignment}", f"\\pos({center_x},{y})"]
        if fade_in or fade_out:
            tags.append(f"\\fad({fade_in},{fade_out})")
        if settings["animation_in"] in {"slide_up", "slide_down"}:
            offset = round(font_size * (1 if settings["animation_in"] == "slide_down" else -1.2))
            tags[1] = f"\\move({center_x},{y + offset},{center_x},{y},0,{round(fade_seconds * 1000)})"
        elif settings["animation_in"] == "zoom":
            tags.append(f"\\fscx82\\fscy82\\t(0,{round(fade_seconds * 1000)},\\fscx100\\fscy100)")
        return " ".join(tags)

    if settings["animation_in"] == "typewriter":
        parts = [item["text"].strip() for item in (segments or []) if item.get("text", "").strip()]
        if not parts:
            parts = text.split()
        step = min(settings["animation_duration"], duration) / max(1, len(parts))
        for visible_count in range(1, len(parts) + 1):
            event_start = settings["start"] + (visible_count - 1) * step
            event_end = settings["end"] if visible_count == len(parts) else settings["start"] + visible_count * step
            prefix = " ".join(parts[:visible_count])
            prefix_lines = _wrap_quote(prefix, box_width, font_size)
            for index, line in enumerate(prefix_lines):
                safe_line = line.replace(",", "，")
                events.append(
                    f"Dialogue: 0,{_ass_time(event_start)},{_ass_time(event_end)},Mood,,0,0,0,,{{{line_tags(index, len(prefix_lines))}}}{safe_line}\n"
                )
    else:
        for index, line in enumerate(lines):
            safe_line = line.replace(",", "，")
            events.append(
                f"Dialogue: 0,{_ass_time(settings['start'])},{_ass_time(settings['end'])},Mood,,0,0,0,,{{{line_tags(index, len(lines))}}}{safe_line}\n"
            )
    path.write_text(header + "".join(events), encoding="utf-8-sig")


def render_mood_video(*, render_id, quote, composition, assets, cancel, progress):
    ffmpeg = executable("ffmpeg", "FFMPEG_PATH")
    width, height = (720, 1280) if composition["resolution"] == "720" else (1080, 1920)
    duration = composition["duration"]
    background, music, text = composition["background"], composition["music"], composition["text"]
    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    target = CLIP_DIR / f"mood-{render_id}.mp4"
    ass_path, gradient_path = WORK_DIR / f"{render_id}.ass", WORK_DIR / f"{render_id}.ppm"
    text_gradient_path = WORK_DIR / f"{render_id}-text-gradient.png"
    visual_gradient_path = WORK_DIR / f"{render_id}-visual-gradient.png"
    error_log = WORK_DIR / f"mood-{render_id}.log"
    process, succeeded = None, False
    try:
        _write_quote_ass(ass_path, quote["text"], composition, width, height, quote.get("segments"))
        args = [ffmpeg, "-hide_banner", "-nostdin", "-y"]
        bg_asset = assets.get(background.get("asset_id")) if background.get("asset_id") else None
        has_video_audio = bool(bg_asset and bg_asset.get("kind") == "background_video" and bg_asset.get("has_audio") and not background["mute_audio"])
        if background["kind"] == "solid":
            args.extend(["-f", "lavfi", "-i", f"color=c={background['color']}:s={width}x{height}:r=30"])
        elif background["kind"] == "gradient":
            _write_gradient(gradient_path, width, height, background["color"], background["color2"])
            args.extend(["-loop", "1", "-framerate", "30", "-i", str(gradient_path)])
        elif bg_asset and background["kind"] == "image":
            args.extend(["-loop", "1", "-framerate", "30", "-i", bg_asset["path"]])
        elif bg_asset and background["kind"] == "video":
            if background["loop"]:
                args.extend(["-stream_loop", "-1"])
            if background["video_start"]:
                args.extend(["-ss", f"{background['video_start']:.3f}"])
            args.extend(["-i", bg_asset["path"]])
        else:
            raise MediaError("Pilih background yang masih tersedia sebelum render.")

        music_asset = assets.get(music.get("asset_id")) if music.get("asset_id") and not music.get("muted", False) else None
        music_index = None
        music_source_has_signal = False
        background_source_has_signal = False
        next_input_index = 1
        if has_video_audio and background["audio_volume"] > 0:
            selected_video_audio_duration = min(duration, max(0.05, bg_asset["duration"] - background["video_start"]))
            source_mean = _audio_mean_volume(ffmpeg, bg_asset["path"], background["video_start"], selected_video_audio_duration)
            if not math.isfinite(source_mean) or source_mean <= -90:
                raise MediaError("Audio background video senyap pada segmen terpilih. Pilih segmen lain, mute audio background, atau gunakan musik.")
            background_source_has_signal = True
        if music_asset:
            available_duration = max(0.0, duration - float(music.get("offset", 0)))
            source_duration = min(
                max(0.0, music["trim_end"] - music["trim_start"]),
                max(0.0, music_asset["duration"] - music["trim_start"]),
            )
            if source_duration < 0.05:
                raise MediaError("Trim musik harus menyisakan sedikitnya 0,05 detik audio.")
            if music["volume"] > 0:
                source_mean = _audio_mean_volume(ffmpeg, music_asset["path"], music["trim_start"], min(source_duration, available_duration))
                if not math.isfinite(source_mean) or source_mean <= -90:
                    raise MediaError("File musik terpilih senyap pada rentang trim. Pilih file lain, ubah trim, atau pilih Tanpa musik.")
                music_source_has_signal = True
            args.extend(["-ss", f"{music['trim_start']:.3f}", "-i", music_asset["path"]])
            music_index = next_input_index
            next_input_index += 1
        if not has_video_audio and not music_asset:
            silence_index = next_input_index
            args.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
            next_input_index += 1
        elif has_video_audio and music_asset:
            silence_index = None
        else:
            silence_index = None

        visual = composition.get("visual") or {}
        gradient_index = None
        if visual.get("gradient_overlay_opacity", 0) > 0:
            _write_gradient_overlay(visual_gradient_path, visual["gradient_top"], visual["gradient_bottom"], visual["gradient_overlay_opacity"])
            args.extend(["-loop", "1", "-framerate", "30", "-i", str(visual_gradient_path)])
            gradient_index = next_input_index
            next_input_index += 1
        text_gradient_index = None
        if text.get("gradient_opacity", 0) > 0:
            _write_text_gradient(text_gradient_path, text["gradient_opacity"], text["y"])
            args.extend(["-loop", "1", "-framerate", "30", "-i", str(text_gradient_path)])
            text_gradient_index = next_input_index
            next_input_index += 1
        filters = _video_filter_graph(
            composition, ass_path, width, height, duration,
            gradient_index=gradient_index, text_gradient_index=text_gradient_index,
        ).split(";")
        if has_video_audio:
            filters.append(
                f"[0:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,volume={background['audio_volume']:.3f},"
                f"apad,atrim=duration={duration:.3f}[bga]"
            )
        if music_asset:
            offset = float(music.get("offset", 0))
            available_duration = max(0.0, duration - offset)
            source_duration = min(
                max(0.0, music["trim_end"] - music["trim_start"]),
                max(0.0, music_asset["duration"] - music["trim_start"]),
            )
            if source_duration < 0.05:
                raise MediaError("Trim musik harus menyisakan sedikitnya 0,05 detik audio.")
            music_play_duration = available_duration if music["loop"] else min(available_duration, source_duration)
            fade_in = min(float(music["fade_in"]), music_play_duration)
            fade_out = min(float(music["fade_out"]), max(0.0, music_play_duration - fade_in))
            music_filter = (
                f"[{music_index}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"atrim=duration={source_duration:.3f},"
                f"asetpts=PTS-STARTPTS,volume={music['volume']:.3f}"
            )
            if music["loop"]:
                music_filter += f",aloop=loop=-1:size={max(1, round(source_duration * 48000))}"
            else:
                music_filter += ",apad"
            delay_ms = round(offset * 1000)
            music_filter += f",adelay={delay_ms}|{delay_ms},atrim=duration={duration:.3f}"
            if fade_in:
                music_filter += f",afade=t=in:st={offset:.3f}:d={fade_in:.3f}"
            if fade_out:
                music_filter += f",afade=t=out:st={max(offset, offset + music_play_duration - fade_out):.3f}:d={fade_out:.3f}"
            filters.append(music_filter + "[musa]")
        if has_video_audio and music_asset:
            filters.append("[bga][musa]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,alimiter=limit=0.95[aout]")
            audio_map = "[aout]"
        elif has_video_audio:
            audio_map = "[bga]"
        elif music_asset:
            audio_map = "[musa]"
        else:
            audio_map = f"{silence_index}:a:0"
        video_encoder = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
        if composition["resolution"] == "1080":
            try:
                available = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10).stdout
                if "h264_amf" in available:
                    video_encoder = ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "vbr_peak", "-b:v", "4000k", "-maxrate", "6000k", "-bufsize", "8000k"]
            except (OSError, subprocess.SubprocessError):
                pass
        args.extend([
            "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", audio_map,
            "-map_metadata", "-1", "-t", f"{duration:.3f}", "-r", "30", *video_encoder,
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
            "-progress", "pipe:1", "-stats_period", "0.5", "-nostats", str(target),
        ])
        with error_log.open("wb") as stderr:
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=stderr, text=True, bufsize=1)
            for line in process.stdout:
                if cancel.is_set():
                    process.terminate()
                    process.wait(timeout=10)
                    raise MediaError("Mood Quotes render dibatalkan.")
                if line.startswith("out_time_us="):
                    try:
                        progress(min(0.99, max(0.01, int(line.split("=", 1)[1]) / 1_000_000 / duration)))
                    except (ValueError, ZeroDivisionError):
                        pass
            process.wait()
            if process.returncode:
                stderr.flush()
                stderr.seek(0, 2)
                size = stderr.tell()
                stderr.seek(max(0, size - 3000))
                details = stderr.read().decode(errors="replace").strip()
                logging.getLogger("klipnara").warning("Mood render %s failed: %s", render_id, details[-1800:])
                if re.search(r"no such filter|unknown filter|option not found", details, re.IGNORECASE):
                    raise MediaError("Build FFmpeg tidak mendukung filter visual yang dipilih. Perbarui FFmpeg atau nonaktifkan efek visual, lalu coba render ulang.")
                raise MediaError("FFmpeg gagal merender video. Periksa codec dan aset media, lalu coba lagi.")
            if not target.is_file() or target.stat().st_size <= 0:
                raise MediaError("FFmpeg selesai tanpa menghasilkan file MP4 yang valid.")
            try:
                metadata = probe(target)
            except MediaError:
                raise MediaError("MP4 hasil render tidak dapat dibaca ffprobe. Periksa log FFmpeg dan aset audio/video.") from None
            if metadata["video_codec"] != "h264" or metadata["audio_codec"] != "aac":
                raise MediaError("MP4 hasil render tidak memiliki stream H.264/AAC yang diwajibkan.")
            if (metadata["width"], metadata["height"]) != (width, height) or abs(metadata["duration"] - duration) > 0.3:
                raise MediaError("Durasi atau resolusi MP4 hasil render tidak sesuai komposisi.")
            if music_source_has_signal or background_source_has_signal:
                output_mean = _audio_mean_volume(ffmpeg, target, 0, duration)
                if not math.isfinite(output_mean) or output_mean <= -90:
                    raise MediaError("Sumber audio memiliki sinyal, tetapi audio MP4 hasil render senyap. Periksa volume, trim, fade, lalu render ulang.")
            succeeded = True
    except FileNotFoundError:
        raise MediaError("FFmpeg executable was not found.") from None
    except subprocess.TimeoutExpired:
        raise MediaError("FFmpeg tidak berhenti setelah pembatalan.") from None
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if process is not None and process.stdout:
            process.stdout.close()
        error_log.unlink(missing_ok=True)
        ass_path.unlink(missing_ok=True)
        gradient_path.unlink(missing_ok=True)
        text_gradient_path.unlink(missing_ok=True)
        visual_gradient_path.unlink(missing_ok=True)
        if not succeeded:
            target.unlink(missing_ok=True)
    if cancel.is_set():
        target.unlink(missing_ok=True)
        raise MediaError("Mood Quotes render dibatalkan.")
    return target
