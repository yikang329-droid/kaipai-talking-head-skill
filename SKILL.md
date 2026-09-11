---
name: kaipai-talking-head
description: Edit vertical Chinese talking-head footage into a Kaipai-inspired social video with concise hook cards, fixed-position Chinese-English subtitles, pitch-preserved 1.1x pacing, a CTA, a separate cover image, and verified MP4 delivery. Use when the user asks for 开拍风格, 口播剪辑, 中英双语字幕, 1.1倍速, or wants to reuse this exact packaging style.
metadata:
  short-description: 开拍风格口播剪辑与双语字幕封面包装
---

# Kaipai talking head

Turn raw vertical talking-head footage into a direct, information-dense social clip while keeping the presenter and real setting as the main visual.

## Defaults

- Deliver square-pixel `1080x1920` CFR video at 30 fps using H.264 High/yuv420p progressive video and AAC-LC 48 kHz mono or stereo audio.
- Use pitch-preserved `1.1x` playback unless the user gives another speed.
- Keep one strong opening hook, at most one middle information card, a closing CTA, fixed Chinese-English subtitles, and one separate cover JPG.
- Treat duration, copy, cut points, card timing, and cover frame as content-dependent. Do not reuse wording or timestamps from an earlier video.
- Keep source footage and rendered media local. Upload media only when the user explicitly requests it.

Read [references/style-spec.md](references/style-spec.md) before designing frames. Read [references/workflow.md](references/workflow.md) before editing or rendering. Use [references/delivery-checklist.md](references/delivery-checklist.md) for final review.

## Workflow

1. Inspect every input with `ffprobe`; cache one word-level verbatim transcript per source.
2. Build the spoken edit from word and sentence boundaries. Remove dead air, false starts, repeated takes, and unrelated tail audio. Never cut inside a word; add 30-200 ms edge padding and 30 ms audio fades at every cut boundary.
3. Write concise Chinese captions from the retained speech, then add natural English below. Translate meaning across adjacent caption beats when English word order requires it. Preserve names, product spelling, numbers, and claims.
4. Apply the same constant playback rate to picture and dialogue. In HyperFrames, set `data-playback-rate` on both media elements and divide authored output timing by the rate. Record the retained pre-speed duration and rate; the rendered duration must equal `edited_duration / playback_rate` within one frame. Do not speed only one track.
5. Build the approved visual treatment. Captions are the highest visual layer and are applied after every overlay.
6. Select a clean source frame with a clear face and useful gesture. Run `scripts/make_cover.py`; do not use a frame from a captioned render or reshape the presenter's face.
7. Run HyperFrames `check`, inspect opening/card/CTA/long-caption/boundary frames, then render high quality.
8. Normalize the final dialogue near `-14 LUFS`. Measure the decoded AAC result and keep true peak at or below `-1 dBTP`; lower the loudnorm target peak and re-encode audio when AAC overshoot exceeds it. Copy the video stream during audio normalization.
9. Run `scripts/validate_delivery.py` against the MP4, cover, SRT, retained pre-speed duration, and playback rate. Deliver only after full decode and visual lip-sync review pass.

## Utilities

```powershell
python scripts/retime_srt.py input.srt output.srt --speed 1.1
python scripts/make_cover.py --input source.mp4 --output cover.jpg --time 12.4 --line "效率为什么没提高？" --line "先改工作流" --emphasis "1:效率:#FFD84D" --emphasis "2:工作流:#43E6C1"
python scripts/validate_delivery.py final.mp4 --cover cover.jpg --srt master.srt --edited-duration 24.0 --playback-rate 1.1
```

If a script fails, fix the input or the edit. Do not waive a failed media, timing, decode, or safe-area check.
