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

| Requested output | Video encoder in current code | Audio |
|---|---|---|
| 720 × 1280 | `libx264`, `veryfast`, CRF 23 | AAC 128 kbps |
| 1080 × 1920 | `h264_amf`, balanced, VBR peak; target 4 Mbps / max 6 Mbps | AAC 128 kbps |

1080p AMF has no automatic x264 fallback in current render code. It needs `h264_amf` and compatible AMD driver. 720p stays CPU x264 by measured quality/speed tradeoff. Center/manual crop only; no face tracking. Subtitle styles are Clean/Bold/Highlight, with user text overrides, size, color, position; timestamps are segments, not words.

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

## Storage and failure behavior

- `DATA_DIR` defaults to `%LOCALAPPDATA%\Klipnara`; `SOURCE_DIR`/`CLIP_DIR` can be separate roots. Legacy managed folders remain readable.
- Work files (`.wav`, `.ass`, logs) use data `work` directory. Logs rotate `klipnara.log` at 2 MB with three backups.
- Path helpers only serve/delete files whose parent is a managed source/clip folder.
- `ffprobe`/FFmpeg binary errors return local errors. Ensure binaries are on `PATH` or set `FFPROBE_PATH`/`FFMPEG_PATH`. 1080p AMF errors require a supported AMF build/driver; choose 720p otherwise.

See [Getting Started](getting-started.md) for install and [Testing and Troubleshooting](testing-and-troubleshooting.md) for actual integration test command and known validation limits.
