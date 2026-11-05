"""Spike 6: proof-of-concept clip ranking with 3 cheap signals on a synthetic
Spanish transcript (written for the spike; real transcripts pending).
Signals: hook (lexicon on first sentence), closure (ends on a punchline-ish
complete sentence), cohesion (mean TF-IDF cosine between sentences)."""
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

# (sentence, is_planted_good_start). Gold moments are 15-30 s blocks starting at "*".
RAW = """
Bueno, pues vamos a empezar, que ya estamos casi todos.
Antes de nada, gracias por venir con este calor.
Como decía antes, esto lo vimos un poco la semana pasada.
Eso que os comenté no lo voy a repetir ahora.
*¿Sabéis cuál es el error número uno al hablar en público?
Hablar demasiado rápido porque tienes miedo al silencio.
El silencio no es tu enemigo, es tu herramienta.
Una pausa de dos segundos hace que todos te miren.
Así que la próxima vez, respira y calla un momento.
Vale, ahora pasamos a la parte de las diapositivas.
Esto, eh, esto se ve un poco pequeño, perdonad.
Y luego, pues, bueno, lo otro que comentábamos.
Él dijo que no, y ya está, no hay más.
*El noventa por ciento de las charlas se olvidan en una hora.
Pero hay una cosa que la gente recuerda durante años.
Una historia personal contada con detalle.
No los datos, no los gráficos, la historia.
Por eso yo empiezo cada charla contando un fracaso mío.
Y os aseguro que funciona siempre.
Bueno, ¿alguna pregunta hasta aquí?
Vale, pues seguimos, que vamos un poco justos de tiempo.
Lo de antes también vale para esto, más o menos.
*Nunca, nunca leáis las diapositivas en voz alta.
Si el público puede leerlo, no te necesita a ti.
Tu trabajo es contar lo que no cabe en la pantalla.
Pon una imagen, una frase y nada más.
Menos texto, más impacto, esa es la regla.
Y con esto terminamos, que ya es la hora.
""".strip().splitlines()

sents = [(s.lstrip("*").strip(), s.startswith("*")) for s in RAW]
# Fake timing: ~2.6 words/s + 0.5 s pause.
t, rows = 0.0, []
for text, gold in sents:
    d = len(text.split()) / 2.6
    rows.append({"text": text, "start": t, "end": t + d, "gold": gold})
    t += d + 0.5

HOOK = re.compile(r"(^¿|\?$|\b(nunca|siempre|error|secreto|nadie|todos|por ciento|número uno)\b|\d)", re.I)
REMATE = re.compile(r"\b(regla|siempre|funciona|clave|historia|herramienta|impacto)\b", re.I)
DANGLING = re.compile(r"^(como decía|eso|esto|lo de antes|y luego|él dijo|vale|bueno)\b", re.I)
FILLER = re.compile(r"\b(eh|pues|bueno|vale)\b", re.I)

tfidf = TfidfVectorizer().fit_transform([r["text"] for r in rows])
sim = (tfidf @ tfidf.T).toarray()

cands = []
for i in range(len(rows)):
    for j in range(i, len(rows)):
        dur = rows[j]["end"] - rows[i]["start"]
        if dur > 30:
            break
        if dur < 15:
            continue
        first, last = rows[i]["text"], rows[j]["text"]
        hook = 1.0 if HOOK.search(first) else 0.0
        hook -= 1.0 if DANGLING.search(first) else 0.0
        closure = 1.0 if REMATE.search(last) else 0.3
        closure -= 0.5 if last.endswith("?") else 0.0
        block = sim[i : j + 1, i : j + 1]
        n = j - i + 1
        cohesion = (block.sum() - n) / (n * n - n)
        filler = sum(len(FILLER.findall(r["text"])) for r in rows[i : j + 1]) / n
        score = 0.45 * hook + 0.3 * closure + 0.25 * min(cohesion * 5, 1) - 0.2 * filler
        cands.append((score, i, j, dur, hook, closure, cohesion))

# Greedy non-overlapping selection.
cands.sort(reverse=True)
picked = []
for c in cands:
    if all(c[2] < p[1] or c[1] > p[2] for p in picked):
        picked.append(c)
    if len(picked) == 5:
        break

gold_starts = {k for k, r in enumerate(rows) if r["gold"]}
hits = 0
for rank, (score, i, j, dur, hook, closure, coh) in enumerate(picked, 1):
    hit = i in gold_starts
    hits += hit
    print(f"#{rank} score={score:.2f} {dur:4.1f}s hook={hook:+.0f} close={closure:.1f} coh={coh:.2f} "
          f"{'GOLD' if hit else '    '} | {rows[i]['text'][:55]} … {rows[j]['text'][:40]}")
print(f"gold starts in top-5: {hits}/{len(gold_starts)}; in top-3: {sum(p[1] in gold_starts for p in picked[:3])}/3")
