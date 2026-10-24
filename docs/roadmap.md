# Product Roadmap

Roadmap captures latest product direction, not a claim that planned code already exists. Source tree and tests remain implementation authority.

## Product direction

- Keep Klipnara personal, single-user, local-first, Windows-first.
- No cloud hosting or mobile app for now.
- Make **Quick Clip from user-supplied timestamps** the primary future workflow.
- Make Whisper/Ollama local AI optional for that primary workflow and other suitable tasks.
- Keep Cloud AI limited to selected features and require explicit user consent per operation.
- Keep FFmpeg as video processing engine.
- Preserve and maintain existing YouTube V1.1 publishing flow.

## Status by feature

| Area | Current source status | Direction |
|---|---|---|
| Quick Clip by timestamp | **Planned.** No timestamp-first form/route or direct-copy workflow exists. Current Create page imports a source and queues transcript + highlight generation. | Implement as default path; allow exact in/out timestamp editing and final FFmpeg processing without requiring AI generation. |
| Whisper transcription | **Implemented; used for fresh sources/cache misses** in current candidate generation. Local whisper.cpp, `small` recommended, `base` fallback, language auto/Indonesian/English. | Make optional for workflows that do not need transcript-based analysis. |
| Ollama highlight analysis | **Implemented, default** local provider; OpenAI/Gemini can replace it with explicit consent. | Keep optional; Quick Clip must work without Ollama. |
| Cloud highlight analysis | **Implemented, optional** OpenAI/Gemini provider with per-job transcript-sharing consent. | Continue feature-specific, opt-in cloud use; no fallback without consent. |
| Cloud transcription | **Planned, not implemented.** No cloud speech-to-text route/provider exists. | Evaluate only for specific user-requested feature, with explicit consent/data disclosure. |
| FFmpeg | **Implemented** for probe/extract/crop/subtitle/render and remains required media engine. | Keep as engine; no replacement planned. |
| YouTube Publishing V1.1 | **Implemented with mocked HTTP tests.** OAuth, approval gate, resumable upload, processing confirmation, history. No real OAuth/upload validation yet. | Preserve; run real Private upload validation after user config. Scheduler may be evaluated only after direct upload proves stable. |
| Mobile / hosted SaaS | **Not implemented.** | No near-term work planned. |

## Suggested next sequence

1. Implement timestamp-first Quick Clip mode as primary workflow; leave current AI highlight generation available as a separate optional path.
2. Ensure Quick Clip works with Whisper and Ollama absent; make transcript/candidate reuse explicit where relevant.
3. Reassess which specific future tasks benefit from Cloud AI; keep request payloads narrow and consent explicit.
4. Configure a real personal YouTube OAuth client, complete one Private upload and verify channel/video ID/privacy/processing in YouTube Studio before extending publishing scope.
5. Consider later scheduled posting, more channels, or social platforms only after local direct YouTube publishing is proven stable and requested.

No estimates or release dates are assigned. Do not label Quick Clip, optional local engines, or Cloud Transcription implemented until matching UI/API/worker code and tests exist.

Current technical structure: [Architecture](architecture.md). Current implemented workflows: [Features and Workflows](features-and-workflows.md).
