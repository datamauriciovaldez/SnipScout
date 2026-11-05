"""SnipScout: find the best moments in a long video and export short clips with word-by-word subtitles."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("snipscout")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"
