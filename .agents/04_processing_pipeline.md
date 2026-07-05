# Audio Processing Pipeline

## Overview

The podcast processing pipeline removes ads from podcast episodes through transcription, AI classification, and audio manipulation.

## Components

### 1. PodcastProcessor (`podcast_processor.py`)
Main coordinator class that orchestrates the entire workflow.

**Key Responsibilities:**
- Download audio from RSS feed
- Manage transcription process
- Coordinate ad classification
- Process audio to remove ads
- Handle errors and retries
- Lock management (prevents concurrent processing of same episode)

**Processing Steps:**
1. Download audio file
2. Transcribe audio to segments
3. Classify segments as ads/content
4. Refine ad boundaries (optional)
5. Process audio to remove ads
6. Update database with results

### 2. TranscriptionManager (`transcription_manager.py`)
Handles audio-to-text conversion.

**Supported Backends:**
- **Local Whisper**: Uses local whisper.cpp or faster-whisper
- **Remote Whisper**: OpenAI Whisper API
- **Groq**: Groq's whisper-large-v3-turbo

**Features:**
- Audio chunking for large files
- Progress tracking
- Retry logic with exponential backoff
- Token rate limiting

### 3. AdClassifier (`ad_classifier.py`)
Uses LLM to identify ad segments in transcripts.

**Process:**
1. Groups transcript segments into chunks
2. Sends chunks to LLM with prompt
3. Parses LLM response for ad labels
4. Stores identifications with confidence scores
5. Handles rate limiting and retries

**LLM Integration:**
- Uses LiteLLM for provider abstraction
- Supports OpenAI, Groq, Claude, etc.
- Configurable concurrency limits
- Token-per-minute rate limiting

**`classify()` return value:** returns `bool`, `True` only if every segment
was classified (the loop reached the end of the transcript with no
exception and no no-progress break). `PodcastProcessor._classify_ad_segments_if_needed`
checks this and marks the job `"failed"` instead of proceeding to the cut
step -- a classification that's aborted or left incomplete no longer ships
the episode unedited with no error surfaced.

**Retry classification (`_is_retryable_error`):** checks real litellm
exception types (`RateLimitError`, `ServiceUnavailableError`,
`APIConnectionError`, `Timeout`, `InternalServerError`) and `.status_code`
(429/503) first, falling back to substring matching on the stringified
error only as a last resort.

### 4. BoundaryRefiner (`boundary_refiner.py`)
Fine-tunes ad segment boundaries for precise cutting.

**Purpose:** 
Intra-segment timestamp refinement to cut exactly at ad boundaries.

**Approach:**
- Re-analyzes audio around detected ad segments
- Uses word-level timestamps when available
- Produces refined start/end times

### 5. AudioProcessor (`audio_processor.py`)
Physical audio file manipulation using FFmpeg.

**Operations:**
- Detect silence (for boundary refinement)
- Cut segments from audio
- Add fade in/out at cut points
- Concatenate segments
- Preserve audio quality

**Configuration:**
- `fade_ms`: Milliseconds of fade at boundaries
- `min_ad_segment_length_seconds`: Minimum ad duration
- `min_ad_segement_separation_seconds`: Merge nearby ads

### 6. PodcastDownloader (`podcast_downloader.py`)
Downloads podcast episodes from RSS feeds.

**Features:**
- Follows redirects
- Handles various audio formats (MP3, M4A, etc.)
- Sanitizes filenames
- Resume capability
- Progress tracking

**`sanitize_title()`:** falls back to a stable hash-based name
(`untitled_<sha1-prefix>`) when the sanitized title would otherwise be
empty/whitespace-only (e.g. an all-emoji RSS title), and truncates to 150
chars.

**Missing/invalid download URL:** raises `DownloadError` (a plain exception
defined in this module), not `flask.abort()` -- this code runs in a
background worker thread with no Flask request context.
`PodcastProcessor.process()`'s generic exception handler catches it and
marks the job failed.

### 7. ProcessingStatusManager (`processing_status_manager.py`)
Tracks and reports processing progress.

**Tracks:**
- Current step (1-4)
- Step name ("Downloading", "Transcribing", "Classifying", "Processing")
- Progress percentage
- Error states

## Data Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Post      │────▶│  Downloader  │────▶│ Audio File  │
│   (GUID)    │     │              │     │  (in/jobs)  │
└─────────────┘     └──────────────┘     └─────────────┘
                                                │
                                                ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Output    │◀────│   Audio      │◀────│  Segments   │
│   (srv/)    │     │  Processor   │     │  (DB table) │
└─────────────┘     └──────────────┘     └─────────────┘
                                                ▲
┌─────────────┐     ┌──────────────┐            │
│  LLM API    │────▶│  Ad Classifier│────────────┘
│  (LiteLLM)  │     │              │
└─────────────┘     └──────────────┘
                            ▲
┌─────────────┐     ┌──────────────┐
│  Whisper    │────▶│ Transcription│
│  (local/API)│     │   Manager    │
└─────────────┘     └──────────────┘
```

## Configuration

Processing behavior controlled via:

**ProcessingSettings:**
- `num_segments_to_input_to_prompt`: Segments per LLM batch
- Prompt templates (system + user)

**OutputSettings:**
- `fade_ms`: Fade duration at cut boundaries
- `min_ad_segment_length_seconds`: Skip short ads
- `min_ad_segement_separation_seconds`: Merge close ads
- `min_confidence`: Minimum confidence threshold

**LLMSettings:**
- Model selection (gpt-4o, claude, etc.)
- API keys and endpoints
- Concurrency and rate limits
- Boundary refinement toggles

**WhisperSettings:**
- Backend selection (local/remote/Groq)
- Model sizes (base, small, medium, large)
- Timeout and retry settings

## Error Handling

- **Retry Logic**: Exponential backoff for API failures
- **Segment Recovery**: Partial results saved on failure
- **Lock Management**: Per-post-GUID lock acquire/release/cleanup is atomic
  under `PodcastProcessor.lock_lock` -- the dict entry is removed once
  released so it doesn't grow unbounded over the process's lifetime. Note:
  there's a known, documented-but-unfixed gap between this in-process lock
  and the DB-level job-cancellation flag -- a stale cancel request can still
  race a completing job's final status write (see comments around
  `_acquire_processing_lock` / `cancel_existing_jobs`).
- **Status Updates**: Real-time job status tracking; classification failures
  now mark the job `"failed"` rather than silently completing (see
  AdClassifier above)

## Performance Considerations

- Audio files stored in `in/` (input) and `srv/` (output) directories
- Transcripts cached in database
- Concurrency limits on LLM calls
- SQLite WAL mode for better concurrency
