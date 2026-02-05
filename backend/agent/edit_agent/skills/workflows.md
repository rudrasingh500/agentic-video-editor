---
id: workflows
title: Workflows
summary: Multi-step editing patterns for common tasks.
category: composite
complexity: complex
---

## interview_cleanup - Interview Cleanup
Summary: Remove silences, add captions, and normalize audio for interviews.
Complexity: complex
Prerequisites: silences.remove, captions.add, mix.loudness

Steps:
1. Call get_timeline_snapshot to understand the current edit.
2. Use silences.remove to delete silent segments (process in reverse order).
3. Use captions.add to add captions where available.
4. Use mix.loudness to normalize dialogue levels.
5. Render and verify with view_render_output.

Verification: Confirm pacing is tight, captions align with speech, and audio levels are consistent.

## highlight_reel - Highlight Reel
Summary: Create a highlight reel by selecting key moments and adding transitions.
Complexity: complex
Prerequisites: cuts.insert, fx.transition

Steps:
1. Use semantic_search or search_transcript to find highlight moments.
2. Insert selected clips with cuts.insert in chronological order.
3. Add transitions between clips with fx.transition.
4. Render and verify for flow and timing.

Verification: Check transitions are smooth and highlight order feels coherent.

## add_broll_sequence - Add B-Roll Sequence
Summary: Overlay b-roll clips to cover specific sections of the main footage.
Complexity: moderate
Prerequisites: brolls.add

Steps:
1. Identify target time ranges for coverage.
2. Search for b-roll assets and select clips.
3. Add a dedicated b-roll track if needed.
4. Insert b-roll clips at the correct timing.
5. Render and verify that b-roll aligns with narration.

Verification: Ensure b-roll timing covers the intended sections without obscuring key visuals.
