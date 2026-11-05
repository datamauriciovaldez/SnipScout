"""Pipeline orchestration over a stored project.

    analyze: prepare_audio → transcribe → understand (segment) → find_moments (score/refine) → clips.json
    render:  subtitles → render → export

Every step reports ``JobEvent``s and honours a ``CancelToken``. The UI, CLI and tests all drive
the core through this module; it never imports UI code.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from snipscout.core import audio
from snipscout.core.binaries import FfmpegBinaries
from snipscout.core.errors import CancelledError, SnipScoutError
from snipscout.core.export import ExportResult, export_clips
from snipscout.core.models import ClipSet, JobEvent, JobState, Project, ProjectStatus, Sentence
from snipscout.core.procs import CancelToken
from snipscout.core.reframe import default_mode, output_size
from snipscout.core.render import RenderOptions
from snipscout.core.segment import segment
from snipscout.core.select import select_clips
from snipscout.core.storage import ProjectStore
from snipscout.core.text.vectors import SentenceEncoder
from snipscout.core.transcribe import QUICK_ANALYSIS_S, SpeechModel, load_model, transcribe

EventSink = Callable[[JobEvent], None]

# Share of the overall bar per stage (transcription dominates on CPU).
ANALYZE_STAGES = {"prepare_audio": 0.05, "transcribe": 0.85, "understand": 0.04, "find_moments": 0.06}


class Pipeline:
    def __init__(
        self,
        store: ProjectStore,
        binaries: FfmpegBinaries,
        *,
        model_loader: Callable[[str], SpeechModel] = load_model,
        encoder: SentenceEncoder | None = None,
    ) -> None:
        self.store = store
        self.bin = binaries
        self.model_loader = model_loader
        self.encoder = encoder

    # -- helpers -----------------------------------------------------------------------------------
    @staticmethod
    def _emitter(on_event: EventSink | None, stages: dict[str, float]) -> Callable[..., None]:
        order = list(stages)

        def emit(stage: str, progress: float, message: str = "", **params: object) -> None:
            if not on_event:
                return
            done = sum(stages[s] for s in order[: order.index(stage)])
            overall = done + stages[stage] * progress
            on_event(
                JobEvent(
                    stage=stage,
                    progress=round(progress, 4),
                    message=message or f"stage.{stage}",
                    params={**params, "overall": round(overall, 4)},
                )
            )

        return emit

    def _fail(self, project: Project, exc: SnipScoutError, on_event: EventSink | None) -> None:
        cancelled = isinstance(exc, CancelledError)
        project.status = ProjectStatus.CANCELLED if cancelled else ProjectStatus.ERROR
        project.error_code = None if cancelled else exc.code
        self.store.save(project)
        if on_event:
            on_event(
                JobEvent(
                    stage="done",
                    state=JobState.CANCELLED if cancelled else JobState.ERROR,
                    message=f"error.{exc.code}",
                    error_code=exc.code,
                )
            )

    def sentences(self, project: Project) -> list[Sentence]:
        transcript = self.store.load_transcript(project.id)
        if transcript is None:
            return []
        wav = self.store.audio_path(project.id)
        rms = audio.rms_envelope_file(wav) if wav.exists() else None
        return segment(transcript.words, language=transcript.language, rms=rms)

    # -- analyze -----------------------------------------------------------------------------------
    def analyze(
        self, project_id: str, *, on_event: EventSink | None = None, cancel: CancelToken | None = None
    ) -> ClipSet:
        project = self.store.load(project_id)
        s = project.settings
        emit = self._emitter(on_event, ANALYZE_STAGES)
        project.status, project.error_code = ProjectStatus.ANALYZING, None
        self.store.save(project)
        try:
            wav = self.store.audio_path(project.id)
            if (
                wav.exists()
                and not s.quick_analysis
                and audio.wav_duration(wav) < project.source.duration - 1.0
            ):
                wav.unlink()  # a previous quick analysis only extracted the first minutes
            if not wav.exists():
                emit("prepare_audio", 0.0)
                audio.extract_audio(
                    self.bin.ffmpeg,
                    project.source,
                    wav,
                    track=s.audio_track,
                    max_seconds=QUICK_ANALYSIS_S if s.quick_analysis else None,
                    on_progress=lambda f: emit("prepare_audio", f),
                    cancel=cancel,
                )
            emit("prepare_audio", 1.0)

            model = self.model_loader(s.model)

            def on_tr(e: JobEvent) -> None:
                emit("transcribe", e.progress, **e.params)

            transcript = transcribe(
                model,
                s.model,
                wav,
                transcript=self.store.load_transcript(project.id),
                language=s.language,
                quick=s.quick_analysis,
                save=lambda t: self.store.save_transcript(project.id, t),
                on_event=on_tr,
                cancel=cancel,
            )
            emit("understand", 0.0)
            sentences = self.sentences(project)
            emit("understand", 1.0, sentences=len(sentences))
            if cancel:
                cancel.raise_if_cancelled()
            emit("find_moments", 0.0)
            clips = select_clips(
                sentences,
                language=transcript.language,
                length=s.clip_length,
                media_duration=project.source.duration,
                encoder=self.encoder,
            )
            clip_set = ClipSet(clips=clips)
            self.store.save_clips(project.id, clip_set)
            emit("find_moments", 1.0, clips=len(clips))
        except SnipScoutError as exc:
            self._fail(project, exc, on_event)
            raise
        project.status = ProjectStatus.ANALYZED
        self.store.save(project)
        if on_event:
            on_event(
                JobEvent(
                    stage="done",
                    progress=1.0,
                    state=JobState.DONE,
                    message="stage.done",
                    params={"clips": len(clip_set.clips), "overall": 1.0},
                )
            )
        return clip_set

    # -- render ------------------------------------------------------------------------------------
    def render_options(
        self, project: Project, *, hardware: bool = False, loudnorm: bool = False
    ) -> RenderOptions:
        w, h = output_size(project.source, project.settings.aspect)
        return RenderOptions(
            width=w,
            height=h,
            mode=default_mode(project.source, project.settings.aspect),
            audio_track=project.settings.audio_track,
            hardware=hardware,
            loudnorm=loudnorm,
        )

    def render(
        self,
        project_id: str,
        *,
        out_dir: Path | None = None,
        on_event: EventSink | None = None,
        cancel: CancelToken | None = None,
        hardware: bool = False,
        loudnorm: bool = False,
    ) -> ExportResult:
        project = self.store.load(project_id)
        clips = self.store.load_clips(project_id)
        transcript = self.store.load_transcript(project_id)
        if clips is None or transcript is None:
            raise SnipScoutError("Analyze the video before rendering.")
        project.status = ProjectStatus.RENDERING
        self.store.save(project)

        def on_clip(i: int, n: int, f: float) -> None:
            if on_event:
                on_event(
                    JobEvent(
                        stage="render",
                        progress=round(((i - 1) + f) / n, 4),
                        message="stage.render",
                        params={"clip": i, "clips": n, "clip_progress": round(f, 4)},
                    )
                )

        try:
            result = export_clips(
                self.bin.ffmpeg,
                project.source,
                transcript.words,
                clips.clips,
                out_dir or (self.store.project_dir(project.id) / "exports"),
                default_style=project.settings.subtitle_style,
                opts=self.render_options(project, hardware=hardware, loudnorm=loudnorm),
                language=transcript.language,
                on_clip_progress=on_clip,
                cancel=cancel,
            )
        except SnipScoutError as exc:
            self._fail(project, exc, on_event)
            raise
        project.status = ProjectStatus.DONE
        self.store.save(project)
        if on_event:
            on_event(
                JobEvent(
                    stage="done",
                    progress=1.0,
                    state=JobState.DONE,
                    message="stage.exported",
                    params={"files": len(result.clips), "folder": str(result.folder)},
                )
            )
        return result
