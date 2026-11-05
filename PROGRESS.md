# PROGRESS

## Done
- H0 spike complete: see docs/spike-report.md. All 6 GO (6 = weak evidence, recheck on real transcripts).

## Decisions
- ffmpeg: system → imageio-ffmpeg (has libass+x264 on win/mac/linux); drop static-ffmpeg. No ffprobe in imageio → PyAV fallback (verify in H1).
- Preview proxy VP9/WebM when H.264 can't play (Qt WebEngine).

## Next
- Author approved H0: embeddings optional (TF-IDF default), Whisper base default. Next: H1. Before pushing: author must auth gh / create GitHub repo.
