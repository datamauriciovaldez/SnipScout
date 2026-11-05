"""Typed errors with stable codes. The UI maps ``code`` to a translated help screen."""


class SnipScoutError(Exception):
    """Base class. ``code`` is stable and used as an i18n key; never change existing codes."""

    code = "unknown"

    def __init__(self, message: str, *, details: str | None = None) -> None:
        super().__init__(message)
        self.details = details  # technical details for "copy technical details"


class FfmpegMissingError(SnipScoutError):
    """No usable ffmpeg (missing, or lacking libass / libx264)."""

    code = "ffmpeg_missing"


class UnsupportedMediaError(SnipScoutError):
    code = "unsupported_media"


class ModelDownloadError(SnipScoutError):
    code = "model_download"


class NoSpeechError(SnipScoutError):
    code = "no_speech"


class OfflineError(SnipScoutError):
    """A network access was attempted while ``SNIPSCOUT_OFFLINE=1``."""

    code = "offline"


class CancelledError(SnipScoutError):
    code = "cancelled"


class FfmpegFailedError(SnipScoutError):
    """ffmpeg exited with an error while processing (render, extraction)."""

    code = "ffmpeg_failed"
