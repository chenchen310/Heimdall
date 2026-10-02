"""The in-app guide stays complete and renders cleanly in both languages.

Two regressions this guards against, both seen in the real app:

- a page added to the sidebar without a guide entry (six pages had none);
- Chinese ``**bold**`` that CommonMark refuses to close — ``**先建立資料。**到`` showed
  the literal asterisks on screen. Streamlit's markdown follows CommonMark, and so does
  ``markdown-it-py``, so rendering every string with it reproduces exactly what the
  browser shows.
"""

from __future__ import annotations

import pytest

from heimdall.ui import _glossary, help_page, i18n
from heimdall.ui._nav import NAV

markdown_it = pytest.importorskip("markdown_it")


def test_every_sidebar_page_and_workbench_tab_has_a_guide_entry() -> None:
    documented = [key for keys in help_page._sections().values() for key in keys]
    expected = [p for pages in NAV.values() for p in pages if p != "Guide"]
    assert set(expected) <= set(documented)
    assert set(help_page._WORKBENCH_TABS) <= set(documented)
    for key in documented:
        entry = help_page._PAGES[key]
        assert entry["en"].strip() and entry["zh"].strip(), key


def test_help_section_is_listed_last() -> None:
    assert list(help_page._sections())[-1] == "Help"


def _markdown_sources() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for lang in ("en", "zh"):
        out.append((f"intro/{lang}", help_page._INTRO[lang]))
        out.append((f"trust/{lang}", help_page._TRUST[lang]))
        out.append((f"conventions/{lang}", help_page._CONVENTIONS[lang]))
        out += [(f"quickstart/{lang}", s) for s in help_page._QUICKSTART[lang]]
        out += [(f"page:{k}/{lang}", v[lang]) for k, v in help_page._PAGES.items()]
        out += [(f"glossary:{e.key}/{lang}", e.text(lang)) for e in _glossary.all_entries()]
    out += [(f"i18n:{k[:40]}", v) for k, v in i18n._ZH.items()]
    return out


def test_no_bold_or_italic_markers_survive_rendering() -> None:
    md = markdown_it.MarkdownIt("commonmark")
    broken = [name for name, text in _markdown_sources() if "**" in md.render(text)]
    assert broken == []


def test_the_known_cjk_bold_trap_is_detected() -> None:
    """The check above would be worthless if markdown-it didn't reproduce the bug."""
    md = markdown_it.MarkdownIt("commonmark")
    assert "**" in md.render("**先建立資料。**到這裡")
    assert "**" not in md.render("**先建立資料**。到這裡")
