"""Build a ~60 s Spanish speech sample with espeak-ng, sentence by sentence,
with known silences, so sentence boundaries are ground truth (sample_truth.json)."""
import json
import subprocess
import wave
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
SR = 16000
SENTENCES = [
    "¿Sabías que el ochenta por ciento de los vídeos se ven sin sonido?",
    "Por eso los subtítulos no son un extra, son obligatorios.",
    "Hoy te voy a enseñar tres trucos que cambiaron mi canal.",
    "El primero es muy sencillo: empieza siempre con una pregunta.",
    "La gente decide en dos segundos si se queda o se va.",
    "El segundo truco es cortar todos los silencios sin piedad.",
    "Un silencio de medio segundo parece una eternidad en el móvil.",
    "Y el tercero, el más importante, es contar una historia con final.",
    "Nadie comparte un vídeo que se corta a la mitad de una idea.",
    "Cuando apliqué estas tres reglas, mis visitas se multiplicaron por cuatro.",
    "No necesitas una cámara cara ni un estudio profesional.",
    "Necesitas claridad, ritmo y un buen cierre.",
    "Pruébalo esta semana y cuéntame qué tal te ha ido.",
]
GAP = 0.7


def tts(text: str, path: Path) -> np.ndarray:
    subprocess.run(["espeak-ng", "-v", "es", "-s", "150", "-w", str(path), text], check=True, timeout=60)
    with wave.open(str(path)) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
        rate = w.getframerate()
    # Resample to 16 kHz (linear interp is fine for a spike).
    n = int(len(data) * SR / rate)
    data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data)
    # Trim leading/trailing near-silence so boundaries are tight.
    idx = np.where(np.abs(data) > 300)[0]
    return data[idx[0] : idx[-1] + 1]


chunks, truth, t = [], [], 0.5
chunks.append(np.zeros(int(0.5 * SR)))
for i, s in enumerate(SENTENCES):
    a = tts(s, OUT / f"_s{i}.wav")
    truth.append({"text": s, "start": round(t, 3), "end": round(t + len(a) / SR, 3)})
    chunks += [a, np.zeros(int(GAP * SR))]
    t += len(a) / SR + GAP
audio = np.concatenate(chunks)
with wave.open(str(OUT / "sample.wav"), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(np.clip(audio, -32768, 32767).astype(np.int16).tobytes())
(OUT / "sample_truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
for p in OUT.glob("_s*.wav"):
    p.unlink()
print(f"duration={len(audio) / SR:.1f}s sentences={len(truth)}")
