# Security policy

SnipScout runs entirely on your computer. Its local server listens on `127.0.0.1` only, on a random free port,
and every request needs the per-session token that the launcher hands to the window (kept in an `HttpOnly`,
`SameSite=Strict` cookie). Requests with an unexpected `Host` or `Origin` header are rejected and CORS is closed.
The only outbound connections are the one-time speech-model download from Hugging Face and, if you use it,
your own Ollama server on `127.0.0.1`. `SNIPSCOUT_OFFLINE=1` blocks every other connection.

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting: on this repository go to
**Security → Report a vulnerability**. Include the version (`snipscout --version`), your operating system and
the steps to reproduce. You should get a first answer within 7 days. Once a fix is released, the report is
credited in the changelog unless you prefer otherwise.

Things that are especially interesting: ways for a web page or another local user to reach the local API,
path traversal in uploads/exports, and anything that makes SnipScout send data off the computer.
