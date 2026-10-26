"""Typed, deterministic visual presets shared by Mood Quotes config and composition."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictVisualModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class VisualEffects(StrictVisualModel):
    motion: Literal["none", "slow_zoom_in", "slow_zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "ken_burns"] = "none"
    motion_intensity: Literal["subtle", "normal", "strong"] = "subtle"
    brightness: float = Field(default=0, ge=-0.3, le=0.3)
    contrast: float = Field(default=1, ge=0.5, le=1.5)
    saturation: float = Field(default=1, ge=0, le=2)
    temperature: float = Field(default=0, ge=-1, le=1)
    vignette: float = Field(default=0, ge=0, le=1)
    grain: int = Field(default=0, ge=0, le=10)
    dark_overlay: float = Field(default=0, ge=0, le=0.7)
    gradient_top: str = Field(default="#26344a", pattern=r"^#[0-9a-fA-F]{6}$")
    gradient_bottom: str = Field(default="#101820", pattern=r"^#[0-9a-fA-F]{6}$")
    gradient_overlay_opacity: int = Field(default=0, ge=0, le=60)
    segment_animation: Literal["fade_in", "fade_out", "fade_up", "slide_up", "gentle_scale", "none"] = "fade_up"


class MoodVisualSettings(VisualEffects):
    schema_version: Literal[1] = 1
    preset_id: str | None = Field(default=None, max_length=64)


class VisualTypography(StrictVisualModel):
    font: str = Field(max_length=40)
    font_size: int = Field(ge=20, le=120)
    font_weight: int = Field(default=600, ge=400, le=800)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    alignment: Literal["left", "center", "right"] = "center"
    x: int = Field(ge=5, le=95)
    y: int = Field(ge=8, le=92)
    line_spacing: float = Field(default=1.25, ge=0.8, le=2.2)
    shadow: bool = True
    outline: bool = False
    opacity: int = Field(default=100, ge=10, le=100)
    gradient_opacity: int = Field(default=0, ge=0, le=80)
    auto_contrast: bool = False


class VisualAnimation(StrictVisualModel):
    text_in: Literal["none", "fade", "slide_up", "slide_down", "typewriter", "zoom"] = "fade"
    text_out: Literal["none", "fade"] = "fade"
    duration: float = Field(default=0.8, ge=0.1, le=5)


class VisualPalette(StrictVisualModel):
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    color2: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class VisualPreset(StrictVisualModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=180)
    category: Literal["cinematic", "dreamy", "minimal", "vintage", "dramatic", "nature"]
    mood_recommendations: list[str] = Field(min_length=1)
    preview: list[str] = Field(min_length=2, max_length=3)
    version: Literal[1] = 1
    background: VisualPalette
    effects: VisualEffects
    typography: VisualTypography
    animation: VisualAnimation
    recommended_music_mood: str = Field(min_length=1, max_length=24)


VISUAL_PRESETS = [
    VisualPreset(
        id="sad-night", name="Sad Night", description="Nuansa malam dingin, kontras lembut, dan vignette dalam.", category="cinematic",
        mood_recommendations=["perasaan-emosi", "sedih", "galau", "kecewa", "kesepian"], preview=["#10182a", "#39435e"], recommended_music_mood="sad",
        background={"color": "#10182a", "color2": "#39435e"},
        effects={"motion": "slow_zoom_in", "motion_intensity": "subtle", "brightness": -0.08, "contrast": 1.12, "saturation": 0.68, "temperature": -0.18, "vignette": 0.48, "grain": 3, "dark_overlay": 0.12, "gradient_top": "#16213a", "gradient_bottom": "#050912", "gradient_overlay_opacity": 20, "segment_animation": "fade_in"},
        typography={"font": "Georgia", "font_size": 48, "font_weight": 400, "color": "#f4f1ed", "alignment": "center", "x": 50, "y": 55, "line_spacing": 1.3, "shadow": True, "outline": False, "opacity": 100, "gradient_opacity": 22, "auto_contrast": False},
        animation={"text_in": "fade", "text_out": "fade", "duration": 0.9},
    ),
    VisualPreset(
        id="rainy-memories", name="Rainy Memories", description="Tone biru kelabu, grain film, dan gerak pan yang pelan.", category="cinematic",
        mood_recommendations=["perasaan-emosi", "sedih", "galau", "rindu", "penyesalan", "nostalgia"], preview=["#283744", "#6c7b87"], recommended_music_mood="mellow",
        background={"color": "#283744", "color2": "#6c7b87"},
        effects={"motion": "pan_down", "motion_intensity": "subtle", "brightness": -0.06, "contrast": 1.08, "saturation": 0.62, "temperature": -0.3, "vignette": 0.3, "grain": 6, "dark_overlay": 0.1, "gradient_top": "#1f3547", "gradient_bottom": "#17212a", "gradient_overlay_opacity": 18, "segment_animation": "slide_up"},
        typography={"font": "Georgia", "font_size": 46, "font_weight": 500, "color": "#f3f4f4", "alignment": "center", "x": 50, "y": 55, "line_spacing": 1.32, "shadow": True, "outline": False, "opacity": 100, "gradient_opacity": 20, "auto_contrast": False},
        animation={"text_in": "slide_up", "text_out": "fade", "duration": 0.75},
    ),
    VisualPreset(
        id="happy-sunshine", name="Happy Sunshine", description="Warna cerah hangat, saturasi hidup, tipografi tegas.", category="nature",
        mood_recommendations=["bahagia-positif", "bahagia", "bersyukur", "menikmati-hidup", "kebahagiaan-sederhana"], preview=["#e9a94b", "#f4d99a"], recommended_music_mood="happy",
        background={"color": "#e9a94b", "color2": "#f4d99a"},
        effects={"motion": "slow_zoom_out", "motion_intensity": "subtle", "brightness": 0.08, "contrast": 1.02, "saturation": 1.28, "temperature": 0.32, "vignette": 0.08, "grain": 0, "dark_overlay": 0, "gradient_top": "#ffd36a", "gradient_bottom": "#ed8b42", "gradient_overlay_opacity": 8, "segment_animation": "gentle_scale"},
        typography={"font": "Arial", "font_size": 50, "font_weight": 700, "color": "#392915", "alignment": "center", "x": 50, "y": 52, "line_spacing": 1.22, "shadow": True, "outline": False, "opacity": 100, "gradient_opacity": 6, "auto_contrast": True},
        animation={"text_in": "zoom", "text_out": "fade", "duration": 0.55},
    ),
    VisualPreset(
        id="golden-hour", name="Golden Hour", description="Highlight keemasan, temperatur hangat, dan gerak menyamping.", category="cinematic",
        mood_recommendations=["bahagia-positif", "bahagia", "optimis", "cinta-hubungan", "romantis", "jatuh-cinta"], preview=["#80523e", "#e2b078"], recommended_music_mood="romantic",
        background={"color": "#80523e", "color2": "#e2b078"},
        effects={"motion": "pan_right", "motion_intensity": "subtle", "brightness": 0.04, "contrast": 1.08, "saturation": 1.12, "temperature": 0.52, "vignette": 0.18, "grain": 2, "dark_overlay": 0.03, "gradient_top": "#ffd18a", "gradient_bottom": "#743d2d", "gradient_overlay_opacity": 14, "segment_animation": "fade_up"},
        typography={"font": "Georgia", "font_size": 50, "font_weight": 500, "color": "#fff4dc", "alignment": "center", "x": 50, "y": 56, "line_spacing": 1.3, "shadow": True, "outline": False, "opacity": 100, "gradient_opacity": 16, "auto_contrast": False},
        animation={"text_in": "fade", "text_out": "fade", "duration": 0.8},
    ),
    VisualPreset(
        id="romantic-dream", name="Romantic Dream", description="Pastel mauve, warna lembut, dan close-up lambat.", category="dreamy",
        mood_recommendations=["cinta-hubungan", "romantis", "jatuh-cinta", "rindu", "hubungan-jarak-jauh"], preview=["#523d52", "#c48b9f"], recommended_music_mood="romantic",
        background={"color": "#523d52", "color2": "#c48b9f"},
        effects={"motion": "slow_zoom_in", "motion_intensity": "subtle", "brightness": 0.02, "contrast": 0.96, "saturation": 0.86, "temperature": 0.18, "vignette": 0.22, "grain": 2, "dark_overlay": 0.04, "gradient_top": "#8f617b", "gradient_bottom": "#392d4b", "gradient_overlay_opacity": 12, "segment_animation": "fade_in"},
        typography={"font": "Georgia", "font_size": 48, "font_weight": 400, "color": "#fff2f4", "alignment": "center", "x": 50, "y": 51, "line_spacing": 1.32, "shadow": True, "outline": False, "opacity": 100, "gradient_opacity": 16, "auto_contrast": False},
        animation={"text_in": "fade", "text_out": "fade", "duration": 1.0},
    ),
    VisualPreset(
        id="motivational-rise", name="Motivational Rise", description="Kontras kuat, warna dalam, dan gerak diagonal membangun.", category="dramatic",
        mood_recommendations=["motivasi-perjuangan", "semangat", "pantang-menyerah", "bangkit-dari-kegagalan", "optimis", "percaya-diri"], preview=["#153b35", "#45a47b"], recommended_music_mood="motivational",
        background={"color": "#153b35", "color2": "#45a47b"},
        effects={"motion": "ken_burns", "motion_intensity": "subtle", "brightness": 0.01, "contrast": 1.18, "saturation": 1.1, "temperature": 0.08, "vignette": 0.14, "grain": 0, "dark_overlay": 0.08, "gradient_top": "#318363", "gradient_bottom": "#09221f", "gradient_overlay_opacity": 16, "segment_animation": "slide_up"},
        typography={"font": "Arial", "font_size": 54, "font_weight": 700, "color": "#f2fff8", "alignment": "center", "x": 50, "y": 52, "line_spacing": 1.2, "shadow": True, "outline": True, "opacity": 100, "gradient_opacity": 20, "auto_contrast": False},
        animation={"text_in": "slide_up", "text_out": "fade", "duration": 0.55},
    ),
    VisualPreset(
        id="calm-morning", name="Calm Morning", description="Kontras rendah, udara sejuk, dan pan vertikal halus.", category="nature",
        mood_recommendations=["healing-self-love", "ketenangan", "menerima-diri-sendiri", "berdamai-dengan-masa-lalu", "kesabaran"], preview=["#b6c9c3", "#e9e2cf"], recommended_music_mood="calm",
        background={"color": "#b6c9c3", "color2": "#e9e2cf"},
        effects={"motion": "pan_up", "motion_intensity": "subtle", "brightness": 0.06, "contrast": 0.94, "saturation": 0.78, "temperature": 0.12, "vignette": 0.08, "grain": 0, "dark_overlay": 0, "gradient_top": "#d8e4dc", "gradient_bottom": "#728d87", "gradient_overlay_opacity": 7, "segment_animation": "fade_in"},
        typography={"font": "Segoe UI", "font_size": 48, "font_weight": 500, "color": "#263e3c", "alignment": "center", "x": 50, "y": 54, "line_spacing": 1.3, "shadow": False, "outline": False, "opacity": 100, "gradient_opacity": 8, "auto_contrast": True},
        animation={"text_in": "fade", "text_out": "fade", "duration": 0.9},
    ),
    VisualPreset(
        id="minimal-aesthetic", name="Minimal Aesthetic", description="Gerak statis, saturasi rendah, dan ruang visual bersih.", category="minimal",
        mood_recommendations=["healing-self-love", "ketenangan", "sedih", "overthinking", "mencintai-diri-sendiri"], preview=["#202423", "#525956"], recommended_music_mood="lofi",
        background={"color": "#202423", "color2": "#202423"},
        effects={"motion": "none", "motion_intensity": "subtle", "brightness": 0, "contrast": 1.03, "saturation": 0.55, "temperature": 0, "vignette": 0.08, "grain": 0, "dark_overlay": 0.08, "gradient_top": "#59645e", "gradient_bottom": "#171a19", "gradient_overlay_opacity": 8, "segment_animation": "fade_in"},
        typography={"font": "Arial", "font_size": 48, "font_weight": 500, "color": "#ffffff", "alignment": "center", "x": 50, "y": 50, "line_spacing": 1.34, "shadow": False, "outline": False, "opacity": 100, "gradient_opacity": 10, "auto_contrast": False},
        animation={"text_in": "typewriter", "text_out": "fade", "duration": 0.8},
    ),
    VisualPreset(
        id="vintage-memories", name="Vintage Memories", description="Sepia hangat, grain lebih nyata, dan vignette film.", category="vintage",
        mood_recommendations=["nostalgia", "kehidupan-refleksi", "waktu", "masa-depan", "rindu"], preview=["#684a39", "#c6a77b"], recommended_music_mood="lofi",
        background={"color": "#684a39", "color2": "#c6a77b"},
        effects={"motion": "slow_zoom_out", "motion_intensity": "normal", "brightness": -0.02, "contrast": 1.12, "saturation": 0.72, "temperature": 0.42, "vignette": 0.42, "grain": 8, "dark_overlay": 0.06, "gradient_top": "#b1875c", "gradient_bottom": "#382b25", "gradient_overlay_opacity": 18, "segment_animation": "fade_in"},
        typography={"font": "Times New Roman", "font_size": 48, "font_weight": 500, "color": "#fff0d2", "alignment": "center", "x": 50, "y": 55, "line_spacing": 1.3, "shadow": True, "outline": False, "opacity": 100, "gradient_opacity": 20, "auto_contrast": False},
        animation={"text_in": "fade", "text_out": "fade", "duration": 1.0},
    ),
    VisualPreset(
        id="dreamy-pastel", name="Dreamy Pastel", description="Highlight pastel, warna terbuka, dan gerak lembut ke kiri.", category="dreamy",
        mood_recommendations=["bahagia-positif", "bahagia", "cinta-hubungan", "romantis", "healing-self-love", "ketenangan"], preview=["#9c9bd0", "#f1bdc8"], recommended_music_mood="calm",
        background={"color": "#9c9bd0", "color2": "#f1bdc8"},
        effects={"motion": "pan_left", "motion_intensity": "subtle", "brightness": 0.08, "contrast": 0.91, "saturation": 1.04, "temperature": 0.08, "vignette": 0.12, "grain": 1, "dark_overlay": 0, "gradient_top": "#cbc6ed", "gradient_bottom": "#edb4c4", "gradient_overlay_opacity": 9, "segment_animation": "gentle_scale"},
        typography={"font": "Georgia", "font_size": 48, "font_weight": 500, "color": "#382f50", "alignment": "center", "x": 50, "y": 52, "line_spacing": 1.32, "shadow": True, "outline": False, "opacity": 100, "gradient_opacity": 8, "auto_contrast": True},
        animation={"text_in": "zoom", "text_out": "fade", "duration": 0.7},
    ),
]


def recommend_visual_presets(mood_ids):
    """Return stable preset order matching any category or subcategory mood ID."""
    selected = set(mood_ids or [])
    return [preset for preset in VISUAL_PRESETS if selected.intersection(preset.mood_recommendations)]


def apply_visual_preset(composition, preset_id):
    """Merge only preset-owned visual fields; preserve user text, assets, music, and manual timing."""
    from copy import deepcopy

    preset = next((item for item in VISUAL_PRESETS if item.id == preset_id), None)
    if preset is None:
        raise ValueError("Visual preset tidak dikenal.")
    result = deepcopy(composition)
    preset_data = preset.model_dump(mode="json")
    visual = {**MoodVisualSettings().model_dump(mode="json"), **result.get("visual", {})}
    visual.update(preset_data["effects"])
    visual.update({"preset_id": preset.id, "schema_version": preset.version})
    result["visual"] = visual

    text = result.setdefault("text", {})
    quote_text, start, end = text.get("text", ""), text.get("start"), text.get("end")
    text.update(preset_data["typography"])
    text.update({"text": quote_text, "animation_in": preset_data["animation"]["text_in"],
                 "animation_out": preset_data["animation"]["text_out"], "animation_duration": preset_data["animation"]["duration"]})
    if start is not None:
        text["start"] = start
    if end is not None:
        text["end"] = end

    background = result.setdefault("background", {})
    if background.get("kind") in {"solid", "gradient"}:
        background.update(preset_data["background"])
    if result.get("text_mode") == "sequential" and result.get("segments_source") != "manual":
        animation = preset_data["effects"]["segment_animation"]
        for segment in result.get("segments", []):
            segment["animation"] = animation
            segment["animation_duration"] = min(preset_data["animation"]["duration"], max(0.1, (segment["end"] - segment["start"]) / 2))
    return result
