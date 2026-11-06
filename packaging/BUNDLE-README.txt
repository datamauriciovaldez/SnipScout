SnipScout - experimental bundle
================================

This folder is an unsigned test build. The recommended install is the release ZIP / tar.gz with the
launcher (see README on GitHub).

- Windows: run SnipScout.exe. SmartScreen or your antivirus may warn because the file is not signed;
  "More info -> Run anyway" if you trust the source. The window needs Microsoft WebView2.
- macOS: the app is not notarized. Right-click SnipScout -> Open, or allow it in System Settings ->
  Privacy & Security.
- Linux: run ./SnipScout. Without GTK/Qt webview libraries it opens in your browser.

The speech model (78-486 MB) is downloaded once on first run. ffmpeg is the build shipped by the
imageio-ffmpeg package. Everything runs locally; no account or key.
