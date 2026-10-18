# `neuron/vendor/` — prebuilt pyturso wheels (decoupled)

Neuron depends on `pyturso` **hard** (not an extra), so it vendors its own wheels
here: the Turso tier installs with **no compiler** on Windows, standalone or via
Gray Matter. `dev/` holds the build-time wheels for an offline `python -m build`.

`pyturso` has no `win_amd64` wheel on PyPI (it's a Rust extension), so the wheels
must be prebuilt. On macOS/Linux pip fetches matching wheels from PyPI, so this
folder is only consulted (via `--find-links`) when it has an ABI match.

## Layout

```
neuron/vendor/
└─ pyturso-0.8.3-cp310-abi3-win_amd64.whl
```

> One wheel covers Python 3.10–3.14: since 0.7 pyturso is built `abi3-py310`
> (PyO3 stable ABI). The old per-minor set (`cp310` … `cp314`) is gone.

## Build fresh (needs Rust + MSVC + Windows SDK)

The Visual Studio **Build Tools** are enough (C++ x64 tools + Windows SDK, ~3 GB);
the full IDE is not needed. From inside `neuron/vendor/`:

```powershell
python -m pip wheel "pyturso==0.8.3" --no-deps --no-binary pyturso -w .
```

Any Python >= 3.10 builds the same abi3 wheel. The
`build-pyturso-win` job in the release workflow rebuilds it on every tag push and
attaches it to the Release.

When you bump the `pyturso` pin, change it in **both** `pyproject.toml`
(the `pyturso==` pin) and the `build-pyturso-win` job in `release.yml`, then rebuild.
