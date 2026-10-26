# ENVIRONMENT — working on the suite

> The rules for developing here that a new session would otherwise rediscover.
> Each one cost at least one wrong result before it was written down.

---

## 1. Tests

Three suites, three processes. From the root of this checkout:

```
python -m pytest neuron/tests -q
python -m pytest gray_matter/tests -q
python -m pytest neurag/tests -q
```

One process for all three fails: `neuron/tests/_mockdeps.py` injects fake
`mcp`/`fastembed` modules that leak into the other suites. The root
`conftest.py` refuses a cross-suite run and prints the three lines above.

**The interpreter must import this checkout.** The three projects are installed
editable (`pip install -e`) into the interpreter that runs the tests. Check it:

```
python -c "import neuron, neurag, gray_matter; print(neuron.__file__)"
```

It must print a path inside this checkout. The MCP server's own venv does not
qualify: it holds a copy of the last install, and it has no pytest.

**A subprocess imports the installed package, not the tree.** A test that
starts `python -c ...` must pass `PYTHONPATH` pointing at the source under
test. Without it, in a worktree, it tests whatever the editable install points
at (`neuron/tests/test_embedding_normalized.py` does it right).

## 2. Line endings

LF everywhere, CRLF for `.ps1`, `.cmd` and `.bat`. `.gitattributes` enforces it
at `git add`, and `test_installer_parity.py` checks the installers on disk.

- On Windows, Python's `write_text` writes CRLF. Pass `newline="\n"`.
- A working copy can turn LF without git noticing: the normalized content is
  identical, so `git status` is clean while the test fails. Delete the file and
  `git checkout -- <file>` to get it back with the right endings.

## 3. Manual checks that do not touch your real setup

| Guard | Why |
|---|---|
| `NEURON_NO_DOTENV=1` | A `.env` with `TURSO_DATABASE_URL` sends any ad-hoc `import neuron` to the shared cloud DB. pytest already skips it; scripts do not. |
| `NS_GRAPHS_DIR=<tmp dir>` | Neuron's graphs go there instead of your memory. |
| `NEURAG_HOME=<tmp dir>` | Same for the NeuRAG vault. |
| `GM_NO_CLIENT_REGISTER=1` | Installers do everything except write the MCP client configs. Isolating `LOCALAPPDATA` is not enough: the configs live in `%APPDATA%`, `~/.claude.json` and `~/.codex`. |

`installer.py`, `uninstaller.py` and `executor.py` touch live processes, client
configs and the disk. Their tests use temp dirs; a real run happens only
locally, with the guards above.

## 4. A code change does not reach the server you are using

The MCP server runs from the suite's venv, a copy made at install time. After a
change, reinstall — the GUI "Ripara" button, or `install.ps1 -Force` — and
restart the client: the workers keep the old code in memory until they restart.

## 5. Where to commit, how to release

Commit here, never on the three mirrors: they receive only `mirror.yml`. The
flow and the release tags are in the README, section "Development";
the per-release checklist for Neuron is in `neuron/docs/RELEASING.md`.
