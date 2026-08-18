# Neuron core audit — 2026-07-15

## Result

The current source tree passes the automated gate:

- **235 tests passed** (`pytest -q`)
- `python -m compileall -q src/neuron`: passed
- `pip check`: no broken requirements
- root skills and packaged skills: byte-identical
- Windows bootstrapper: compiled successfully, 12.8 KB

The first focused run exposed two real skill-copy drifts. They were synchronized and
the full suite was rerun successfully. A separate test run initially hit a Windows
temporary-directory permission problem; rerunning with a project-local pytest base
directory passed.

## Core areas checked

### Persistence and Turso

- Local SQLite, local PyTurso and remote Turso paths are covered by the test suite.
- Remote retries recreate the client between attempts instead of retrying a stale
  connection.
- `libsql://` can fall back to `https://` when the WebSocket transport is rejected.
- Saves remain dirty after failure, so a later turn can retry the write.
- Shared-store writes are additive by default; destructive reconciliation is guarded.

### Embeddings and search

- Embedding dimensions are checked against the configured vector dimension.
- Embedding cache keys include the embedder identity.
- Python cosine fallback is bounded to `[-1, 1]`.
- Seed and active graph results are merged by best similarity rather than returning
  early from the first database.
- Model mismatches skip incompatible vectors instead of silently mixing spaces.

### Extraction and graph quality

- Accent folding and Italian/English stop words are tested.
- Sentiment matching avoids substring false positives such as `download` → `down`.
- Compound keywords are length-validated before promotion.
- Curation, duplicate screening, typed links and no-self-link rules are covered.

### Human and AI entry points

- `install.cmd` is the first-run Windows entry point (double-click); `install.sh`
  on Linux and `install.command` on macOS. All three are thin launchers over the
  installer engine and forward their arguments. No compiled binary is shipped:
  the old `NeuronInstaller.exe` bootstrapper was removed (2026-07-29) after its
  in-tree copy went stale — four launchers, one per platform, is the whole story.
- Python is not a prerequisite on Windows: `install.ps1` installs the newest
  3.14.x from python.org (per-user, no admin) when none in 3.10–3.14 is found.
- `install.ps1 -Yes` is genuinely non-interactive: every prompt is gated behind
  one `$Ask` flag, so a scripted or console-less caller never blocks on stdin.
- Turso setup has a GUI form that validates, probes read/write access and saves only
  after a successful test; the token is not placed on a command line or in the log.
- The GUI command bar validates subcommands and the packaged skills match their root
  sources.

## Deliberate limits

- Tkinter is intentionally retained for zero-dependency, cross-Python compatibility.
  It can look modern with custom dark styling, but it cannot provide the native
  rounded controls, animations and typography of Qt or a browser UI without adding a
  runtime dependency. The bootstrapper is independent of this limitation.
- The bootstrapper is Windows-focused and must travel with `install.ps1` and `vendor/`;
  it is not a standalone offline package. Code signing is still required to remove
  SmartScreen warnings for public distribution.
- Cloudflare quick tunnels remain ephemeral; the GUI can restart them, but a stable
  public URL requires a named Cloudflare tunnel.

## Operational conclusion

The core is green under the current test gate. The remaining release-readiness work is
distribution-oriented: sign the EXE, test the bootstrapper on clean Windows 10/11
machines, and decide whether a browser/Qt frontend is worth its additional runtime.
