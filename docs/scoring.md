# How clips are chosen

SnipScout **proposes; you decide.** Selection uses no language model by default: a heuristic scorer that can
explain every number it gives. All weights live in one file,
[`src/snipscout/core/scoring/weights.toml`](../src/snipscout/core/scoring/weights.toml).

## 1. Candidates

The transcript is split into sentences (`segment.py`). Every window that starts at a sentence start, ends at a
sentence end and fits the chosen length (short 15–30 s, medium 30–60 s, long 60–90 s) is a candidate. Clips never
cut a word. A cheap pre-score (opening + ending + autonomy) keeps the best `candidates_prefilter` (400) windows.

## 2. Seven signals (each 0–1)

| Signal | Weight | What raises it | What lowers it |
|---|---|---|---|
| **hook** | 3.0 | First sentence is a question (+0.6), has a number (+0.35), emphasis or contrast words (up to +0.5), direct address (+0.15) | — |
| **pace** | 1.0 | 1.8–3.8 words/s | Pauses longer than 1.2 s inside the clip, filler words ("eh", "um", "o sea"…) |
| **energy** | 1.0 | Loudness variation (lively voice) and loudness above the video's median | Flat, quiet delivery |
| **cohesion** | 1.5 | Sentences share vocabulary/meaning: mean pairwise cosine of TF-IDF vectors (or local embeddings if installed) | Topic jumps |
| **closure** | 2.5 | Ends with terminal punctuation, a closer/punchline phrase, a pause after | Ends on an open question or a dangling word ("and", "but", "that") |
| **autonomy** | 2.0 | Makes sense alone | Opens with references to earlier context ("as I said", "that's why", "he said"), starts mid-flow |
| **confidence** | 0.5 | High word probabilities from the transcription | Mumbled or noisy audio |

Word lists are in `core/text/data/es.json` and `en.json` (same keys; other languages use both).

**Score** = Σ (weight × signal) ÷ Σ weights × 100. The Results screen shows each signal's contribution in points
("why it works"), and signals above 0.6 become readable reasons ("Opens with a question", "Clean ending"…).

## 3. Diversity and final cut

Candidates are re-ranked with **MMR** (`mmr_lambda` 0.75): each pick balances its score against similarity to clips
already picked, and overlapping windows are excluded. The top `top_k` (12) are shown; the best 3 are pre-ticked.
Each clip gets 0.15 s of padding without touching its neighbours.

Titles, hooks and keywords are **extractive**: the hook is the opening sentence trimmed cleanly (≤ ~80 characters),
the title is the most representative sentence, keywords come from TF-IDF. Nothing is invented.

## 4. Optional: local AI re-ranking

If Ollama already runs on the computer, *Improve with local AI* sends each of the top 15 clips' text to a model the
user chose and asks for a 0–10 rating and a title. New order = 0.5 × heuristic score + 0.5 × rating × 10.
Safeguards: loopback only; the excerpt goes in as JSON data and the system prompt forbids following instructions in
it; replies must match a JSON schema (Pydantic); 120 s timeout per clip; a failed clip keeps its heuristic result,
and if none succeeds nothing changes. Suggested titles are shown next to the clip and applied only with *Use*.

## 5. Tuning and honesty

`scripts/eval_scoring.py` measures how many annotated "good moments" appear in the top K for a weights file:

```bash
uv run python scripts/eval_scoring.py --weights src/snipscout/core/scoring/weights.toml
```

Status: weights are **hand-tuned on synthetic transcripts** (recall@5 = 7/7 on two annotated synthetic talks, weak
evidence). They have not yet been validated on real videos. Annotations of real talks (`eval/annotations/*.json`:
transcript + preferred ranges) are welcome — see [CONTRIBUTING](../CONTRIBUTING.md).
