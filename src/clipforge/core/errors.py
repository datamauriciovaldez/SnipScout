"""Typed errors with stable codes. The UI maps ``code`` to a translated help screen."""


class ClipForgeError(Exception):
    """Base class. ``code`` is stable and used as an i18n key; never change existing codes."""

    code = "unknown"

    def __init__(self, message: str, *, details: str | None = None) -> None:
        super().__init__(message)
        self.details = details  # technical details for "copy technical details"


class FfmpegMissingError(ClipForgeError):
    """No usable ffmpeg (missing, or lacking libass / libx264)."""

    code = "ffmpeg_missing"


class UnsupportedMediaError(ClipForgeError):
    code = "unsupported_media"


class ModelDownloadError(ClipForgeError):
    code = "model_download"


class NoSpeechError(ClipForgeError):
    code = "no_speech"


class OfflineError(ClipForgeError):
    """A network access was attempted while ``CLIPFORGE_OFFLINE=1``."""

    code = "offline"
