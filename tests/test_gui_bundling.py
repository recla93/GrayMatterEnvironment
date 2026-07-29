"""One GUI, reachable from every tool — including a standalone install.

The control center is Gray Matter's (`gray_matter.webgui`). There is no second
GUI: Neuron and NeuRAG both route `<tool> gui` to it. For that to work when
Gray Matter was never installed as a peer, each ships GM's wheel inside its own
package and installs it offline on first launch.

The stale-wheel trap: that wheel is a pinned copy. Bump Gray Matter and the
peers keep bootstrapping the OLD control center, silently, forever — a
standalone user gets a GUI a version behind and nothing says so.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

VENDOR_DIRS = {
    "neuron": ROOT / "neuron" / "src" / "neuron" / "_gm_vendor",
    "neurag": ROOT / "neurag" / "_gm_vendor",
}


def _gm_version() -> str:
    body = (ROOT / "gray_matter" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', body)
    assert m, "gray_matter/__init__.py has no __version__"
    return m.group(1)


@pytest.mark.parametrize("tool", sorted(VENDOR_DIRS))
def test_each_tool_bundles_the_control_center(tool):
    """A standalone install must be able to open the GUI with no network."""
    wheels = list(VENDOR_DIRS[tool].glob("gray_matter-*.whl"))
    assert wheels, (
        f"{tool} ships no Gray Matter wheel — `{tool} gui` would need PyPI, so a "
        "standalone/offline install has no control center at all")
    assert len(wheels) == 1, f"{tool} bundles {len(wheels)} GM wheels: {wheels}"


@pytest.mark.parametrize("tool", sorted(VENDOR_DIRS))
def test_the_bundled_wheel_matches_the_current_gray_matter(tool):
    """THE stale-release guard. Bumping GM without rebuilding these wheels ships
    peers that bootstrap an older control center and never mention it."""
    wheel = next(iter(VENDOR_DIRS[tool].glob("gray_matter-*.whl")))
    bundled = wheel.name.split("-")[1]
    current = _gm_version()
    assert bundled == current, (
        f"{tool} bundles Gray Matter {bundled} but the source tree is {current} — "
        f"rebuild it:  python -m build --wheel gray_matter  "
        f"then replace {wheel.relative_to(ROOT)}")


@pytest.mark.parametrize("tool", sorted(VENDOR_DIRS))
def test_the_wheel_actually_ships_in_the_package(tool):
    """A wheel on disk that setuptools does not package is not bundled at all."""
    toml = (ROOT / tool / "pyproject.toml").read_text(encoding="utf-8")
    assert "_gm_vendor" in toml, (
        f"{tool}/pyproject.toml does not declare _gm_vendor in package-data — "
        "the wheel would be missing from the built distribution")


@pytest.mark.parametrize("tool,module", [("neuron", "neuron"), ("neurag", "neurag")])
def test_there_is_no_second_gui(tool, module):
    """One GUI. A tool-local GUI module is the thing that drifts."""
    pkg = ROOT / ("neuron/src/neuron" if tool == "neuron" else "neurag")
    strays = [p.name for p in pkg.glob("*gui*.py")]
    assert not strays, f"{tool} has its own GUI module(s) {strays} — the control center is Gray Matter's"
