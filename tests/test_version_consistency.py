"""Every place that states the version must state the same one.

v6.3.0 shipped with `__version__ = "6.2.0"` while pyproject.toml said 6.3.0.
Nothing compared them, so the wrong number travelled inside the wheel and the
only way to find it was to go looking. A version is a claim the package makes
about itself: four files repeat it, and a claim repeated in four places without
a check is four chances to be wrong.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"',
                  (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert m, "pyproject.toml has no version"
    return m.group(1)


def _sources(version: str) -> dict:
    """Every file that repeats the version, and what it says. Files that simply
    do not carry one are absent from the result rather than silently passing."""
    out = {}

    init = ROOT / "src" / "neuron" / "__init__.py"
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"), re.M)
    if m:
        out["__init__.py"] = m.group(1)

    readme = ROOT / "README.md"
    if readme.is_file():
        m = re.search(r"badge/version-([0-9][^-\s]*)-", readme.read_text(encoding="utf-8"))
        if m:
            out["README badge"] = m.group(1)

    changelog = ROOT / "CHANGELOG.md"
    if changelog.is_file():
        m = re.search(r"^##\s+([0-9][^\s(]*)", changelog.read_text(encoding="utf-8-sig"), re.M)
        if m:
            out["CHANGELOG top entry"] = m.group(1)

    return out


def test_every_statement_of_the_version_agrees():
    want = _pyproject()
    said = _sources(want)
    assert said, "no file besides pyproject.toml states the version — expected at least __init__.py"
    wrong = {where: got for where, got in said.items() if got != want}
    assert not wrong, (
        f"pyproject.toml says {want}, but " +
        "; ".join(f"{where} says {got}" for where, got in sorted(wrong.items())) +
        " — bump them together or the wheel ships a number that is not true"
    )


def test_the_changelog_documents_this_version():
    """A release whose CHANGELOG still opens on the previous version is a
    release nobody wrote down."""
    want = _pyproject()
    changelog = ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        return
    top = re.search(r"^##\s+([0-9][^\s(]*)", changelog.read_text(encoding="utf-8-sig"), re.M)
    assert top and top.group(1) == want, (
        f"CHANGELOG opens on {top.group(1) if top else '(nothing)'}, "
        f"pyproject.toml is at {want}"
    )
