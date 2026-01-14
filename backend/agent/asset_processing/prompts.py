"""
Analysis prompts for extracting metadata from media assets.

These prompts are used with Gemini 3 Flash to analyze images, videos, and audio files
and extract structured metadata for use in video editing workflows.
"""

IMAGE_ANALYSIS_PROMPT = """You are an expert media analyst. Analyze this image thoroughly and extract comprehensive metadata that will be used by AI agents for video editing, content search, and asset management.

## Required Output (JSON)

Provide a JSON object with the following fields:

### 1. summary (string, required)
A detailed 2-4 sentence description of the image. Include:
- The main subject(s) and their actions/state
- Setting/environment/location context
- Mood, atmosphere, or emotional tone
- Any notable composition or visual style elements
- Time of day or lighting conditions if apparent

### 2. tags (array of strings, required)
Provide 10-20 specific, searchable tags covering:
- Primary subjects (people, objects, animals)
- Actions or states depicted
- Colors (dominant and accent colors)
- Emotions/mood (e.g., "joyful", "melancholic", "tense")
- Visual style (e.g., "minimalist", "cluttered", "high-contrast")
- Setting type (e.g., "indoor", "outdoor", "urban", "nature")
- Lighting (e.g., "natural-light", "backlit", "golden-hour")
- Composition (e.g., "close-up", "wide-shot", "symmetrical")
- Use case tags (e.g., "b-roll-suitable", "hero-image", "background")

### 3. transcript (object or null)
Extract ALL visible text using OCR as a structured object:
{
  "text": "The complete extracted text as a single string",
  "segments": [
    {"position": "top-left", "text": "Logo text here"},
    {"position": "center", "text": "Main heading"}
  ],
  "has_text": true
}
Return null only if absolutely no text is visible.

### 4. faces (array of objects or null)
For each detected face/person, provide:
{
  "id": "face_1",
  "description": "Detailed description of the person",
  "apparent_age_range": "20-30",
  "gender_presentation": "masculine/feminine/androgynous",
  "expression": "smiling, eyes closed",
  "position": "center-left, foreground",
  "clothing_visible": "blue jacket, white shirt",
  "notable_features": "glasses, beard, tattoo on arm"
}
Return null if no faces/people are visible.

### 5. objects (array of objects)
List significant objects with:
{
  "name": "laptop",
  "description": "Silver MacBook Pro on wooden desk",
  "position": "center",
  "prominence": "primary" | "secondary" | "background",
  "brand": "Apple" (if identifiable, else null)
}

### 6. colors (object)
{
  "dominant": ["#hex1", "#hex2", "#hex3"],
  "palette_description": "Warm earth tones with blue accents",
  "brightness": "bright" | "medium" | "dark",
  "saturation": "vibrant" | "muted" | "monochrome"
}

### 7. technical (object)
{
  "estimated_quality": "high" | "medium" | "low",
  "aspect_ratio_category": "landscape" | "portrait" | "square",
  "has_transparency": true | false,
  "is_screenshot": true | false,
  "is_graphic_design": true | false,
  "is_photograph": true | false
}

Return ONLY the JSON object, no additional text or markdown."""


VIDEO_ANALYSIS_PROMPT = """You are an expert video analyst. Analyze this video thoroughly and extract comprehensive metadata that will be used by AI agents for video editing, content search, clip selection, and asset management.

## Required Output (JSON)

Provide a JSON object with the following fields:

### 1. summary (string, required)
A detailed 3-5 sentence description covering:
- Main content/subject matter and narrative arc
- Key actions, events, or transformations
- Visual style, cinematography approach
- Overall mood, tone, and pacing
- Target audience or apparent purpose

### 2. tags (array of strings, required)
Provide 15-25 specific, searchable tags covering:
- Content type (e.g., "interview", "b-roll", "tutorial", "vlog", "product-demo")
- Subjects (people, objects, locations)
- Actions depicted (e.g., "walking", "talking", "cooking")
- Genres/themes (e.g., "technology", "lifestyle", "corporate")
- Mood/tone (e.g., "upbeat", "serious", "casual", "professional")
- Visual style (e.g., "cinematic", "handheld", "static-shots")
- Pacing (e.g., "fast-paced", "slow", "dynamic")
- Quality indicators (e.g., "4k", "professional-lighting", "amateur")
- Use case tags (e.g., "intro-suitable", "background-footage", "testimonial")

### 3. transcript (object or null)
Complete transcription of ALL spoken words as a structured object:
{
  "text": "The complete transcript as a single string",
  "segments": [
    {"timestamp_ms": 0, "speaker": "Speaker 1", "text": "Hello and welcome..."},
    {"timestamp_ms": 5000, "speaker": "Speaker 2", "text": "Thanks for having me..."}
  ],
  "speakers": ["Speaker 1", "Speaker 2"],
  "has_speech": true
}
Include:
- Speaker identification for multiple speakers in segments
- Timestamps in milliseconds for each segment
- Non-speech audio cues in brackets within text (e.g., "[applause]", "[music plays]")
Return null only if there is absolutely no speech.

### 4. events (array of objects, required)
Chronicle significant moments with precise timestamps:
{
  "timestamp_ms": 5000,
  "timestamp_formatted": "00:05",
  "event_type": "scene_change" | "action" | "speech_start" | "music_change" | "text_overlay" | "transition",
  "description": "Detailed description of what happens",
  "importance": "high" | "medium" | "low",
  "suggested_use": "Could be used as intro clip" (optional editorial suggestion)
}
Aim for 10-30 events depending on video length.

### 5. notable_shots (array of objects, required)
Identify visually compelling or editorially useful frames:
{
  "timestamp_ms": 12000,
  "timestamp_formatted": "00:12",
  "description": "Wide establishing shot of city skyline at sunset",
  "shot_type": "wide" | "medium" | "close-up" | "extreme-close-up" | "aerial",
  "camera_movement": "static" | "pan" | "tilt" | "zoom" | "tracking" | "handheld",
  "composition_notes": "Rule of thirds, subject on left",
  "suggested_use": "thumbnail" | "b-roll" | "hero-shot" | "transition-point",
  "visual_quality": "high" | "medium" | "low"
}
Identify 5-15 notable shots.

### 6. audio_features (object, required)
{
  "has_speech": true | false,
  "has_music": true | false,
  "has_sound_effects": true | false,
  "speech_percentage": 75,
  "music_description": "Upbeat electronic background music" | null,
  "audio_quality": "professional" | "amateur" | "poor",
  "background_noise": "none" | "minimal" | "noticeable" | "significant",
  "mood_from_audio": "energetic", "calm", "tense", etc.
}

### 7. faces (array of objects or null)
For each person appearing in the video:
{
  "id": "person_1",
  "description": "Adult male in business attire",
  "appears_at_ms": [0, 15000, 45000],
  "screen_time_percentage": 60,
  "role": "main_subject" | "interviewer" | "interviewee" | "background" | "presenter",
  "speaking": true | false,
  "notable_features": "Glasses, grey hair"
}

### 8. scenes (array of objects)
Break video into logical scenes/segments:
{
  "scene_number": 1,
  "start_ms": 0,
  "end_ms": 15000,
  "duration_formatted": "00:15",
  "description": "Opening sequence with logo animation",
  "location": "Studio" | "Outdoor" | "Office" | etc.,
  "mood": "professional",
  "key_content": "Introduction of topic"
}

### 9. technical (object)
{
  "estimated_resolution": "1080p" | "4k" | "720p" | etc.,
  "frame_rate_estimate": "24fps" | "30fps" | "60fps",
  "is_screen_recording": true | false,
  "has_text_overlays": true | false,
  "has_watermark": true | false,
  "orientation": "landscape" | "portrait" | "square"
}

Return ONLY the JSON object, no additional text or markdown."""


AUDIO_ANALYSIS_PROMPT = """You are an expert audio analyst. Analyze this audio file thoroughly and extract comprehensive metadata that will be used by AI agents for video editing, music selection, podcast production, and asset management.

## Required Output (JSON)

Provide a JSON object with the following fields:

### 1. summary (string, required)
A detailed 2-4 sentence description covering:
- Type of audio content (music, speech, podcast, sound effect, etc.)
- Main subject matter or theme
- Mood, energy level, and emotional tone
- Notable characteristics or standout elements
- Potential use cases

### 2. tags (array of strings, required)
Provide 10-20 specific, searchable tags covering:
- Content type (e.g., "music", "podcast", "interview", "sound-effect", "voiceover")
- Genre (for music: "electronic", "jazz", "ambient", etc.)
- Mood/emotion (e.g., "uplifting", "melancholic", "aggressive", "peaceful")
- Energy level (e.g., "high-energy", "calm", "building", "dynamic")
- Instrumentation (e.g., "piano", "synth", "acoustic-guitar", "orchestral")
- Vocal characteristics (e.g., "male-vocal", "female-vocal", "choir", "spoken-word")
- Use cases (e.g., "background-music", "intro-music", "transition-sound", "podcast-intro")
- Quality (e.g., "studio-quality", "lo-fi", "professional")

### 3. transcript (object or null)
For speech/vocals, provide complete transcription as a structured object:
{
  "text": "The complete transcript or lyrics as a single string",
  "segments": [
    {"timestamp_ms": 0, "speaker": "Host", "text": "Welcome to the show..."},
    {"timestamp_ms": 15000, "speaker": "Guest", "text": "Thanks for having me..."}
  ],
  "speakers": ["Host", "Guest"],
  "has_speech": true
}
Include:
- Speaker identification for multiple speakers in segments
- Timestamps in milliseconds for each segment
- Non-speech sounds in brackets within text (e.g., "[music interlude]", "[laughter]")
- For songs with lyrics, transcribe all lyrics in text field with verse structure
Return null only if there is no speech or lyrics.

### 4. events (array of objects)
Identify significant audio moments:
{
  "timestamp_ms": 30000,
  "timestamp_formatted": "00:30",
  "event_type": "beat_drop" | "key_change" | "tempo_change" | "speaker_change" | "music_start" | "silence" | "climax" | "outro_start",
  "description": "Main beat drops with heavy bass",
  "intensity": "high" | "medium" | "low",
  "edit_suggestion": "Good cut point for video transition"
}

### 5. audio_features (object, required)
{
  "bpm": 128 (estimated beats per minute, null for non-rhythmic),
  "key": "A minor" | null,
  "time_signature": "4/4" | null,
  "energy_level": "high" | "medium" | "low",
  "energy_progression": "builds" | "steady" | "fades" | "dynamic",
  "has_speech": true | false,
  "has_music": true | false,
  "has_singing": true | false,
  "speech_to_music_ratio": 0.7 (0-1 scale, null if not applicable),
  "dynamic_range": "wide" | "compressed" | "moderate",
  "audio_quality": "professional" | "amateur" | "lo-fi"
}

### 6. structure (object, for music)
{
  "intro_ms": 0,
  "intro_end_ms": 8000,
  "verse_timestamps_ms": [8000, 45000],
  "chorus_timestamps_ms": [23000, 68000],
  "bridge_ms": 90000,
  "outro_start_ms": 120000,
  "total_duration_ms": 145000,
  "loopable_sections": [{"start_ms": 23000, "end_ms": 45000, "description": "Main chorus, loops cleanly"}]
}
Return null for non-music audio.

### 7. speakers (array of objects, for speech content)
{
  "id": "speaker_1",
  "description": "Adult male with American accent",
  "role": "host" | "guest" | "narrator" | "interviewee",
  "speaking_time_percentage": 60,
  "voice_characteristics": "deep, calm, professional"
}

### 8. technical (object)
{
  "estimated_bitrate": "high" | "medium" | "low",
  "channels": "stereo" | "mono",
  "has_background_noise": true | false,
  "noise_level": "none" | "minimal" | "noticeable" | "significant",
  "clipping_detected": true | false,
  "silence_percentage": 5
}

Return ONLY the JSON object, no additional text or markdown."""
