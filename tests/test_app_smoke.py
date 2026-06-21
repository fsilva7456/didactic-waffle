"""Headless smoke test of the Streamlit app via AppTest — verifies the shell
(and any added pages) render without raising. This is the e2e recipe for
dashboard work units."""
from __future__ import annotations

from pathlib import Path

import pytest

from strava_dash.paths import REPO_ROOT

HOME = REPO_ROOT / "src" / "strava_dash" / "app" / "Home.py"


def test_home_renders(fixture_db):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(HOME), default_timeout=30).run()
    assert not at.exception
    # With data loaded, the title and metrics should be present.
    assert any("Strava Training Dashboard" in m.value for m in at.title)


def test_pages_render(fixture_db):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    pages_dir = REPO_ROOT / "src" / "strava_dash" / "app" / "pages"
    for page in sorted(pages_dir.glob("*.py")):
        at = AppTest.from_file(str(page), default_timeout=30).run()
        assert not at.exception, f"page {page.name} raised: {at.exception}"
