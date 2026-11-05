# PROGRESS

## Done
- H0 spike (partial): see docs/spike-report.md. Spikes 1, 4, 5 GO; 6 weak evidence; 2, 3 BLOCKED (huggingface.co denied by build sandbox network policy).

## Decisions
- ffmpeg: system → imageio-ffmpeg (has libass+x264 on win/mac/linux); drop static-ffmpeg. No ffprobe in imageio → PyAV fallback (verify in H1).
- Preview proxy VP9/WebM when H.264 can't play (Qt WebEngine).

## Next
- Waiting for author: allow huggingface.co, then run `spikes/s2_whisper.py tiny base` + spike 3; then H1.
