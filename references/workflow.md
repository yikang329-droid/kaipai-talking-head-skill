# Production workflow

## 1. Intake and transcript

Probe resolution, frame rate, duration, codecs, rotation, sample rate, and channel count. Store all session artifacts under an `edit/` directory beside the staged input unless project rules specify another location.

Use word-level verbatim transcription. Cache the transcript and retain filler words, repeats, and silence gaps so cut decisions remain auditable.

## 2. Spoken edit

Choose cuts from the transcript first, then inspect frames around candidate boundaries. Preserve intent and natural breath. Snap cuts to word boundaries with 30-200 ms padding. For multiple retained ranges, extract each range and add 30 ms audio fades before concatenation.

Record retained source ranges and their output offsets in a small EDL or project note. Sum the retained ranges to get the pre-speed edited duration. Captions must use output-timeline timestamps after cuts.

## 3. Bilingual captions

Keep each caption to one spoken idea. Chinese is the primary line; English is the supporting line. Translate for natural meaning and allow an English phrase to continue across adjacent Chinese beats. Do not add claims, soften the speaker's position, or translate product names.

Create an external bilingual SRT for audit even when captions are burned into the render. Use millisecond timestamps, monotonic cue order, and no overlaps.

## 4. Constant retime

For HyperFrames media, use the same rate on video and audio:

```html
<video class="clip" data-start="0" data-duration="OUTPUT_DURATION" data-playback-rate="1.1" muted playsinline></video>
<audio id="dialogue" data-start="0" data-duration="OUTPUT_DURATION" data-playback-rate="1.1" data-volume="1"></audio>
```

Compute `output_time = edited_time / rate`. Scale every clip start, duration, GSAP position, duration, and stagger. At 30 fps, render `ceil(output_duration * 30)` frames; a tail difference below one frame is normal. Pass the EDL's pre-speed duration and configured rate to the delivery validator so an original-speed render cannot pass as the retimed version.

Use `setpts=(PTS-STARTPTS)/rate` plus `atempo=rate` only when the renderer cannot apply a constant rate natively. Keep pitch preservation enabled.

## 5. Composition

Use full-frame footage. Put the opening hook in the upper safe area, keep the middle card to one content block, and place the CTA in the same upper system near the close. Captions sit above every overlay in z-order.

The opening should reveal in two short phases. A subtle punch-in may cover a real jump cut. Use deterministic, seekable animation without looping decoration.

## 6. Cover

Choose a clean frame from the original source with direct eye contact or a useful gesture. Avoid blink frames, motion blur, captioned frames, and crops that lose the hand. Place the headline in available negative space without covering eyes, mouth, or the key gesture.

Use the bundled cover script as a starting point and inspect the actual JPG at full resolution.

## 7. Render and loudness

Run the project's HyperFrames `check`, then render high quality. Normalize audio in two loudnorm passes while copying video. Start with `I=-14`, `LRA=7`, and `TP=-2.5` before AAC encoding. Re-measure the decoded file with `ebur128=peak=true`; accept approximately `-14 LUFS` and a decoded true peak no higher than `-1 dBTP`.

Constrain the normalized output to the rendered video duration so AAC padding does not extend the container. Confirm the normalized output keeps the exact video packet hash when compared with the render master.

## 8. Review

Inspect frames at the opening reveal, every real cut boundary, the longest English subtitle, the middle card entrance and exit, CTA entrance, and the final half-second. Watch dialogue around the opening and every cut boundary to confirm lip sync; stream start/end alignment alone cannot prove internal sync. Run a full decode before delivery.
