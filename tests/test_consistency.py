"""Things that must agree across files, so a release can't ship half-updated."""

import json
import re
from pathlib import Path

from grab import __version__, integrate

REPO = Path(__file__).resolve().parent.parent
EXT = integrate.package_dir("extension")


def test_extension_version_matches_package_version():
    assert json.loads((EXT / "manifest.json").read_text())["version"] == __version__


def test_extension_talks_to_the_host_the_package_registers():
    host = re.search(r'const HOST = "([^"]+)"', (EXT / "background.js").read_text()).group(1)
    assert host == integrate.HOST_NAME


def test_every_file_the_manifest_names_exists():
    m = json.loads((EXT / "manifest.json").read_text())
    named = {
        m["background"]["service_worker"],
        m["action"]["default_popup"],
        *m["icons"].values(),
        *m["action"]["default_icon"].values(),
    }
    assert all((EXT / n).is_file() for n in named), sorted(n for n in named if not (EXT / n).is_file())
    assert (EXT / "scan.js").is_file() and (EXT / "popup.js").is_file()


def test_documented_extension_id_matches_the_pinned_key():
    assert integrate.extension_id() in (REPO / "README.md").read_text()


def test_changelog_has_an_entry_for_this_version():
    assert re.search(rf"^## \[{re.escape(__version__)}\]", (REPO / "CHANGELOG.md").read_text(), re.M)
