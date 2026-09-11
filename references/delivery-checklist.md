# Delivery checklist

## Content

- Opening reaches the subject immediately and the retained speech stays truthful.
- Cuts do not split words, clip consonants, or leave unrelated tail audio.
- Chinese and English captions match the retained speech and preserve names and claims.

## Picture

- MP4 is square-pixel `1080x1920` CFR at 30 fps, H.264 High, yuv420p, progressive.
- Presenter, eyes, mouth, and meaningful gestures remain visible.
- Opening hook, information card, CTA, and captions stay inside platform-safe areas.
- The longest Chinese and English lines fit without clipping or awkward wrapping.
- The cover is a `1080x1920` RGB JPEG from an uncaptioned source frame.

## Sound and timing

- Video and dialogue use the same playback rate and stay lip-synced.
- AAC-LC audio is 48 kHz; decoded loudness is about `-14 LUFS` and true peak is `<= -1 dBTP`.
- The edit report records retained pre-speed duration and playback rate; output duration matches their quotient within one frame.
- Video/audio start and tail differences are no more than one video frame.
- SRT cues are ordered, non-overlapping, and end no later than the video plus one frame.

## Technical gate

- HyperFrames `check` passes when HyperFrames is used.
- The final MP4 decodes fully with `ffmpeg -v error -i final.mp4 -f null -`.
- `scripts/validate_delivery.py` exits `0` for the MP4, cover, bilingual SRT, retained pre-speed duration, and playback rate.
- Sampled final-render frames show no overflow, overlap, blank media, stale overlay, or subtitle hidden behind a card.

## Deliverables

- Final normalized MP4.
- Separate cover JPG.
- Bilingual master SRT.
- A short edit record with source ranges, playback rate, duration, loudness, and verification result.
