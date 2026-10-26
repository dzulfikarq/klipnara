# Video Processing

`backend/clipper/media.py` owns source probing, ingest, audio extraction helpers, ASS subtitles and FFmpeg export. FFmpeg/ffprobe are runtime binaries; Klipnara does not bundle them.

## Ingest and source validation

- File upload accepts `.mp4`/`.mov`, rejects empty files, enforces default 2 GiB cap (`CLIPPER_MAX_UPLOAD_BYTES`) and checks for at least 1 GiB free before writes.
- `probe()` accepts FFmpeg-recognized MP4/MOV formats, requires a video stream, allows audio to be absent, and validates duration from 1 second through 4 hours plus positive dimensions. AI Smart Clip needs audio only when it must create a transcript; Quick Clip does not.
- Direct URL import accepts HTTPS on port 443 only. It expects a direct media response (video MIME type or `application/octet-stream`), not a YouTube/site page. It allows at most three redirects, revalidates each target, resolves public addresses and pins TLS connection to the resolved address to reduce DNS-rebinding/private-network risk.
- Source files are hashed during ingest. Database stores metadata and path; local file is retained until source deletion.

## Transcription audio extraction

On a cache miss, job worker runs FFmpeg with `loudnorm=I=-20:TP=-1.5:LRA=11`, mono, 16 kHz, signed 16-bit PCM WAV. `whisper.cpp` emits JSON timestamps; WAV and Whisper JSON work files are deleted after use. Transcript itself is stored in SQLite for later edits/renders.

## Render pipeline

`render()` creates `{clip_id}-{job_id}.mp4` under `CLIPPER_CLIP_DIR` (default local `clips`). It calculates absolute in/out from candidate start plus trim, scales to fill portrait, applies center/manual crop percentages, optionally burns ASS subtitles, maps video/audio, writes H.264 + AAC, `yuv420p`, and `+faststart` MP4. Quick Clip disables subtitles initially and uses selected source timestamps directly. For a source without audio, renderer adds finite-duration silent stereo AAC through FFmpeg `anullsrc`; source file is not modified.

### Mood Quotes compositor

`mood_renderer.py` writes temporary ASS/gradient assets and streams one background plus optional music through FFmpeg; it never stores video frames in Python memory. Background can be uploaded still, generated solid/gradient, or project/Source Library video. A selected segment starts at `video_start`; video loops when requested, otherwise `tpad=clone` holds its last frame. Active background audio and selected music are resampled to stereo 48 kHz before mixing. Music supports trim, start offset, mute, volume, sample-loop, fades, and `amix`/`alimiter`; FFmpeg delays the music stream by the composition offset and places fades on that output timeline. Server validates audible span/fade bounds against asset duration. Muted/zero-volume selections intentionally allow silent AAC; active selected audio is signal-checked before render and output audio is checked when an active source has signal. Silent/corrupt active audio fails with actionable error. No music means background audio or silent AAC.

Single Text uses one positioned ASS quote and preserves legacy timing. Sequential Text uses ordered timed segments with per-segment fade/fade-up/slide/scale animation. Validated provider segments are reused when they fit; otherwise deterministic local sentence/clause segmentation and word-weighted timing run. Short discourse openers merge with following clauses; unsafe connector boundaries are avoided. Text layout is preflighted against the safe frame. ASS typography includes preset/user font weight, color, outline, shadow and animation. Text is escaped into ASS, never shell-concatenated. Bounded values, validated colors, project-owned asset IDs, and argv-based FFmpeg calls constrain inputs. Output metadata is stripped. ASS/gradient/log files and failed partial MP4 are removed on success/failure/cancel; startup cleans interrupted-render artifacts. A hard kill between render and DB update can leave an orphan final file.

`composition.visual` drives the existing renderer, not a parallel pipeline. Background is scaled-to-fill and cropped to 9:16 first. User-selected still/video backgrounds may then use bounded `zoompan` (4/8/12% maximum zoom for Subtle/Normal/Strong) for slow zoom, pan, or Ken Burns. Crop stays within the filled frame, so no black bars; zoom can soften low-resolution source detail. Color controls map to `eq` and `colorbalance`; atmosphere uses `vignette`, optional low-strength `noise`, `drawbox`, and one generated RGBA gradient overlay. Text backing remains separate. Effects are chained in one video filtergraph with existing ASS overlay and audio graph. There is no GPU-only filter or added video dependency; software effects can increase CPU time, especially grain/1080p. A missing FFmpeg filter returns an actionable unsupported-filter error. Soft glow is not implemented. Output encoder selection and audio mix contract remain unchanged.

Mood composition defaults: 720×1280, 30 FPS, 5–40 seconds; 1080×1920 is optional. 720 uses `libx264 veryfast CRF 23`; 1080 uses `h264_amf` on builds that provide it, otherwise CPU x264 fallback. Render progress comes from FFmpeg `out_time_us`. Previous render paths stay intact until a replacement succeeds. Approved render hash is stored separately in `mood_renders`; any composition/quote edit invalidates review without deleting the old file. Timeline selection, zoom, and snap are UI-only; segment/background/music edits remain composition fields, and render jobs retain immutable quote/composition snapshots.

Mood fonts use Windows system families Arial, Georgia, Segoe UI, Tahoma, Trebuchet MS, and Times New Roman. Klipnara does not bundle or download fonts. Preview uses matching system font names and FFmpeg/libass resolves installed system fonts; fallback depends on installed OS fonts. No third-party font redistribution occurs. Text layout is preflighted against output frame and returns a clear validation error if it cannot fit.

Step 3 Live Preview uses CSS transforms/filters and the same saved effect values; no FFmpeg or AI request runs per edit. Image/video background motion is simulated from the still image or cached video thumbnail. Thumbnail API seeks requested frame, scales to at most 720×1280, and caches JPEG per asset/0.1-second frame in its project `previews` folder. Frontend debounces frame changes and ignores stale loads; server retains at most 12 recent frames per video. The timeline playhead synchronizes local music preview offset, trim, loop, fades, and mute. Preview Penuh plays actual background video/audio and music with the same composition timing. CSS temperature/grain/vignette and browser typography are approximations; FFmpeg/libass output can differ. Compare editor, Preview Penuh, and MP4 final. Safe Area is editor-only.

| Requested output | Video encoder in current code | Audio |
|---|---|---|
| 720 × 1280 | `libx264`, `veryfast`, CRF 23 | AAC 128 kbps |
| 1080 × 1920 | `h264_amf`, balanced, VBR peak; target 4 Mbps / max 6 Mbps | AAC 128 kbps |

The existing source-clip 1080p AMF path has no automatic x264 fallback; it needs `h264_amf` and a compatible AMD driver. Mood Quotes uses AMF when available and CPU x264 fallback otherwise. 720p stays CPU x264 by measured quality/speed tradeoff. Source-clip crop is center/manual only; no face tracking. Subtitle styles are Clean/Bold/Highlight, with user text overrides, size, color, position; timestamps are segments, not words.

FFmpeg reports `out_time_us` for progress. A cancelled/failed render removes partial new output and preserves previous render path; successful replacement updates DB first and then deletes old file. Output is not approved automatically; every successful render is `needs_review` with no approval fingerprint.

## Recorded render checks

Recorded 23 Oct 2026 on i3-9100F, 15.9 GiB RAM, RX 570 4 GiB, FFmpeg 9.0.2 Gyan build, with a 19.5 s CPU baseline and 37.5–37.8 s measured highlight renders. Results below are specific to this driver/build/settings.

| Case | Encoder | Encoder time | File size | Comparison |
|---|---|---:|---:|---|
| 720p Clean/Bold/Highlight | libx264 veryfast CRF 23 | 14.1–18.5 s | 10.5–11.5 MB | baseline |
| Equivalent 720p AMF probe | h264_amf VBR peak, 2.3 Mbps | 9.8 s | 11.5 MB | luma SSIM 0.9723 vs x264 |
| 1080p prior CPU highlight | libx264 veryfast CRF 23 | 31.4 s | 19.21 MB | baseline |
| 1080p final app highlight | h264_amf VBR peak, 4 Mbps | 18.6 s | 19.76 MB | 1.69× faster; luma SSIM 0.9805 |

AMF speed gain at 720p was modest with lower SSIM, so app keeps x264 there. At 1080p AMF was 1.69× faster in this run with a 2.8% larger file and visually similar inspected frame.

Recorded output QA used a saved 38.26 s candidate from a 25:45 local source; analysis/transcription were not rerun. Seven style/crop exports: all H.264/AAC, exact 9:16, complete FFmpeg decode, no detected black intervals, A/V duration delta 0.012–0.028 s and trim within 0.03 s of target. A/V quality check covered selected test clips, not arbitrary media. 1080p evidence covers the selected clip, not a broad range of input formats/content.

Quick Clip real and synthetic E2E measurements, including duration, CPU/RSS sampling, audio/no-audio output and source immutability, are in [Testing and Troubleshooting](testing-and-troubleshooting.md). Runs used 720p x264 and short intervals; GPU utilization was not sampled, and measurements are not a broad performance benchmark.

Mood Quotes synthetic FFmpeg E2E was recorded 24 Oct 2026 on the same Windows 11/i3-9100F/RX 570 workstation. All four 4-second 720p renders passed ffprobe: short looping synthetic video + background audio/music mix (0.67 s, 763,549 bytes), solid color + silent AAC (0.48 s, 17,498 bytes), PPM gradient + silent AAC (0.97 s, 29,707 bytes), and still image + silent AAC (0.78 s, 17,125 bytes). All were H.264/AAC 720×1280 at 30 FPS, with Unicode/ASS animation and no AI calls. These historical runs predate V2.4 offset/mute cases; new V2.4 synthetic cases remain unrun. These tiny synthetic renders validate the path, not real-content quality or longer/1080p performance.

## Storage and failure behavior

- `DATA_DIR` defaults to `%LOCALAPPDATA%\Klipnara`; `SOURCE_DIR`/`CLIP_DIR` can be separate roots. Legacy managed folders remain readable.
- Work files (`.wav`, `.ass`, logs) use data `work` directory. Logs rotate `klipnara.log` at 2 MB with three backups.
- Path helpers only serve/delete files whose parent is a managed source/clip folder.
- `ffprobe`/FFmpeg binary errors return local errors. Ensure binaries are on `PATH` or set `FFPROBE_PATH`/`FFMPEG_PATH`. 1080p AMF errors require a supported AMF build/driver; choose 720p otherwise.

See [Getting Started](getting-started.md) for install and [Testing and Troubleshooting](testing-and-troubleshooting.md) for actual integration test command and known validation limits.
