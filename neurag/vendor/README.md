# `neurag/vendor/` — prebuilt pyturso wheels (decoupled)

NeuRAG is designed to run standalone, so it vendors its **own** `pyturso` wheels
here instead of borrowing them from `neuron/vendor/`. This lets the Turso
(vector-SQL) tier install with **no compiler** on Windows even when Neuron is not
present next to NeuRAG.

`pyturso` has no `win_amd64` wheel on PyPI (it's a Rust extension), so the wheels
must be prebuilt. On macOS/Linux pip fetches matching wheels from PyPI, so this
folder is only consulted (via `--find-links`) when it has an ABI match.

## Layout

```
neurag/vendor/
└─ pyturso-0.8.3-cp310-abi3-win_amd64.whl
```

> One wheel covers Python 3.10–3.14: since 0.7 pyturso is built `abi3-py310`
> (PyO3 stable ABI). The old per-minor set (`cp310` … `cp314`) is gone.

## Build fresh (needs Rust + MSVC + Windows SDK)

The Visual Studio **Build Tools** are enough (C++ x64 tools + Windows SDK, ~3 GB);
the full IDE is not needed. From inside `neurag/vendor/`:

```powershell
python -m pip wheel "pyturso==0.8.3" --no-deps --no-binary pyturso -w .
```

Any Python >= 3.10 builds the same abi3 wheel. The
`build-pyturso-win` job in the release workflow rebuilds it on every tag push and
attaches it to the Release.

When you bump the `pyturso` pin, change it in **both** `pyproject.toml`
(`[turso]` extra) and the `build-pyturso-win` job in `release.yml`, then rebuild.
