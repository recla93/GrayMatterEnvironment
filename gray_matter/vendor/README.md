# `gray_matter/vendor/` — prebuilt pyturso wheels (decoupled)

Gray Matter builds the **shared venv** the whole suite installs into, so it
vendors its own `pyturso` wheels here instead of reaching into `neuron/vendor/`.
This lets the Turso (vector-SQL) tier install with **no compiler** on Windows for
whichever peers come along — including a GM+NeuRAG install with no Neuron.

GM's own bridge store is stdlib `sqlite3`; these wheels are installer payload,
not a Gray Matter dependency.

`pyturso` has no `win_amd64` wheel on PyPI (it's a Rust extension), so the wheels
must be prebuilt. On macOS/Linux pip fetches matching wheels from PyPI, so this
folder is only consulted (via `--find-links`) when it has an ABI match.

## Expected layout (full set)

```
gray_matter/vendor/
├─ pyturso-0.6.1-cp310-cp310-win_amd64.whl
├─ pyturso-0.6.1-cp311-cp311-win_amd64.whl
├─ pyturso-0.6.1-cp312-cp312-win_amd64.whl
├─ pyturso-0.6.1-cp313-cp313-win_amd64.whl
└─ pyturso-0.6.1-cp314-cp314-win_amd64.whl
```

> One wheel = one Python minor version. A `cp312` wheel installs only on Python
> 3.12. A real release needs the full 3.10–3.14 set.

## Build fresh (needs Rust + MSVC + Windows SDK)

**Your Python version only** (quick, for testing the no-compile path):

```powershell
python -m pip wheel "pyturso==0.6.1" --no-deps --find-links . -w .
```

Run it from inside `gray_matter/vendor/`. It drops
`pyturso-0.6.1-cp<XY>-cp<XY>-win_amd64.whl` here, where `<XY>` is your Python
minor (e.g. `cp313` for 3.13).

**Full set (3.10–3.14):** don't build these by hand — the
`.github/workflows/release.yml` → `build-pyturso-win` job compiles all five on
`windows-latest` runners on every tag push (`v*`) and attaches them to the
Release. That is the source of truth for a published set.

When you bump the `pyturso` pin, change it in **both** `pyproject.toml`
(the peers' `[turso]` extra) and the `build-pyturso-win` job in `release.yml`, then rebuild.
