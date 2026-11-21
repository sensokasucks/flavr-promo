"""
The panel shell every settings page is drawn in (owner 2026-11-21: "update the whole webpage part to
be how Stream Core handles its menus and tabs"). Same idea as Stream Core's admin: a menu down the
left with a few groups, and a row of tabs across the top of the page for the pages of that group.

  Articles   Article editor (flavrpromo/article_editor.py), Line picker (host_picker.py)
  Hosts      Pictures (settings_page.py, pose pools), Host lines (settings_page.py),
             Character cards (card_page.py)
  Bot        Settings (settings_page.py: KoboldCpp, hosts on/off), Commands (command_forms.py)

``frame`` draws one page in it. Who calls it: settings_page.py (re-exports ``frame``), card_page.py,
article_editor.py, command_forms.py and host_picker.py. A new page = one line in NAV (the label is
what a page passes as its ``heading``) plus its routes. Plain HTML + CSS, no script and no build
step, so other groups can still run their own copy. No password, like the rest of port 3871 (home
network only; never forward the port).
"""

from __future__ import annotations

import html
from typing import Any, Tuple

# (group, ((url, label), ...)): keep each url in step with that page's add_routes.
NAV: Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...] = (
    ("📰 Articles", (("/settings/article", "📰 Article editor"), ("/hosts/pick", "🎙️ Line picker"))),
    ("🎭 Hosts", (("/settings/pictures", "🖼️ Pictures"), ("/settings/lines", "💬 Host lines"),
                 ("/settings/cards", "🧾 Character cards"))),
    ("⚙️ Bot", (("/settings", "⚙️ Settings"), ("/settings/commands", "⌨️ Commands"))),
)
PAGES = tuple(p for _, pages in NAV for p in pages)         # flat list (older callers)

STYLE = (
    ":root{--pink:#f72ca2;--teal:#2ae0d4;--bg:#1b1018;--card:#2a1a28;--line:#3d2a3b}"
    "*{box-sizing:border-box}body{margin:0;font-family:sans-serif;background:var(--bg);color:#eee;display:flex;"
    "min-height:100vh}a{color:var(--teal)}"
    ".side{width:200px;flex:none;background:#150c13;border-right:2px solid var(--line);padding:14px 10px;"
    "position:sticky;top:0;align-self:flex-start;height:100vh}"
    ".side h2{font-size:15px;margin:2px 8px 14px;color:var(--pink)}"
    ".side a{display:block;padding:9px 12px;border-radius:8px;color:#ddd;text-decoration:none;margin-bottom:4px}"
    ".side a:hover{background:var(--card)}.side a.on{background:var(--pink);color:#fff;font-weight:bold}"
    ".main{flex:1;min-width:0;max-width:1150px;padding:16px 22px 40px}"
    ".tabs{display:flex;gap:6px;flex-wrap:wrap;border-bottom:2px solid var(--line);margin-bottom:14px}"
    ".tabs a,.tabs b{padding:8px 14px;border-radius:8px 8px 0 0;text-decoration:none;color:#ccc}"
    ".tabs b{background:var(--card);color:#fff;border-bottom:3px solid var(--teal)}"
    ".tabs a:hover{background:#231521}h1{margin:6px 0 14px;font-size:26px}"
    "section{border-bottom:2px solid var(--line);padding:10px 0 20px}"
    "label{display:block;margin:8px 0}input:not([type=checkbox]):not([type=radio]):not([type=file]),select{width:min(420px,90%)}"
    "input[type=number]{width:90px!important}button{padding:7px 12px;border-radius:8px;border:0;font-weight:bold;"
    "background:var(--pink);color:#fff;cursor:pointer}button.alt{background:#3a2d3a}.help,small{color:#aab;display:block}"
    ".saved,.test{background:var(--teal);color:#000;padding:8px;border-radius:8px;white-space:pre-wrap}"
    ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}"
    ".pic{background:var(--card);border-radius:10px;padding:10px}.pic img,.pic .none{width:100%;height:150px;"
    "object-fit:contain;background:#0e0f14;border-radius:8px;display:flex;align-items:center;justify-content:center}"
    ".pic b{display:block;margin-top:6px}.pic input[type=file]{width:100%;margin:6px 0}"
    "textarea{width:100%;font-size:14px;background:#0e0f14;color:#eee;border:1px solid #555;border-radius:6px}"
    "nav.in{margin:6px 0 10px}pre{white-space:pre-wrap;background:#0e0f14;padding:10px;border-radius:8px;font-size:13px}"
    "@media(max-width:760px){body{display:block}.side{width:auto;height:auto;position:static;display:flex;"
    "flex-wrap:wrap;gap:4px;align-items:center;border-right:0;border-bottom:2px solid var(--line)}"
    ".side h2{margin:0 10px 0 4px}.side a{margin:0}.main{padding:12px}}"
)


def _e(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def frame(title: str, heading: str, body: str, saved: str = "", style: str = "") -> str:
    """A whole page in the panel: the menu of groups on the left, the tabs of ``heading``'s group on
    top (``heading`` = a label from NAV; an unknown one gets no tab row), then the page ``body``.
    ``saved``: the note shown after a save. ``style``: extra CSS for that page."""
    group = next((g for g, pages in NAV if any(n == heading for _, n in pages)), "")
    side = "".join(f'<a href="{pages[0][0]}"{" class=on" if g == group else ""}>{_e(g)}</a>' for g, pages in NAV)
    pages = next((pg for g, pg in NAV if g == group), ())
    tabs = ""
    if len(pages) > 1:
        tabs = "<div class=tabs>" + "".join(f"<b>{_e(n)}</b>" if n == heading else f'<a href="{u}">{_e(n)}</a>'
                                            for u, n in pages) + "</div>"
    note = f'<p class=saved>{_e(saved)}</p>' if saved else ""
    return ("<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>{_e(title)}</title><style>{STYLE}{style}</style></head><body>"
            f"<div class=side><h2>FlaVR Promo</h2>{side}</div>"
            f"<div class=main>{tabs}<h1>{_e(heading)}</h1>{note}{body}</div></body></html>")
