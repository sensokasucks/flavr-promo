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
what a page passes as its ``heading``) plus its routes. Plain HTML + CSS and one small inline script
(SCRIPT, no library and no build step, so other groups can still run their own copy); every page
works without the script too, it only adds comfort (owner 2026-11-22: live preview, folding cards,
drag to reorder, "add the GUI changes to the other parts of the webpage"):
  * folding: a ``<section>`` that starts with an ``<h2>`` folds when its heading is clicked, and
    ``<details class=card id=...>`` cards remember whether they were open (sessionStorage, per page
    and per ``data-foldkey`` on the page, e.g. the draft);
  * live forms: ``<form data-live>`` saves itself (its normal POST with action=save) when a menu or
    tick box changes, or a moment after typing stops, then swaps the parts of the page marked
    ``data-swap`` (``always``: after every save, e.g. a preview picture; ``rebuild``: only after a menu
    / tick box change, e.g. the list of cards) with the same part of the answer (matched by
    ``data-swap-id``). ``data-nolive`` on an element keeps its fields out of it;
  * drag to reorder: the ``<details id>`` children of a ``data-draglist`` element can be dragged by
    their summary; the new order goes in the form's hidden ``order`` field (ids, comma separated) and
    is posted with action=order. A ``data-foldall="open"`` / ``"close"`` button opens / folds every card. No password, like the rest of port 3871 (home
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
    # the shared look (2026-11-22): dark fields, sections and cards as rounded panels, folding, drag marks
    "input:not([type=checkbox]):not([type=radio]):not([type=file]):not([type=color]),select,textarea{background:#0e0f14;"
    "color:#eee;border:1px solid #4a3547;border-radius:6px;padding:5px 8px;font-size:14px}"
    "input:focus,select:focus,textarea:focus{outline:2px solid var(--teal);outline-offset:1px}"
    "input[type=checkbox],input[type=radio]{accent-color:var(--pink)}button:hover{filter:brightness(1.15)}"
    "button[disabled]{opacity:.35;cursor:default}"
    ".main>section,.main>form>section{background:var(--card);border:1px solid var(--line);border-radius:12px;"
    "padding:4px 16px 14px;margin:12px 0}section>h2{font-size:18px;margin:10px 0 6px}"
    "h2.foldh{cursor:pointer;user-select:none}h2.foldh::before{content:'▾';color:var(--teal);margin-right:8px}"
    "section.folded>h2.foldh::before{content:'▸'}section.folded>:not(h2){display:none}section.folded{padding-bottom:4px}"
    "details.card{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:10px 0}"
    "details.card>summary{list-style:none;cursor:pointer;padding:9px 14px;display:flex;gap:10px;align-items:center;"
    "flex-wrap:wrap;user-select:none}details.card>summary::-webkit-details-marker{display:none}"
    "details.card>summary::before{content:'▸';color:var(--teal)}details.card[open]>summary::before{content:'▾'}"
    "details.card>.inner{padding:4px 14px 12px;border-top:1px solid var(--line)}"
    "summary .what{color:#aab;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:46%}"
    "summary .acts{margin-left:auto;display:flex;gap:6px;align-items:center}summary .acts button{padding:5px 10px}"
    ".grip{cursor:grab;color:#889;font-size:18px}details.dragging{opacity:.4}"
    "details.dropbefore{box-shadow:0 -4px 0 var(--teal)}details.dropafter{box-shadow:0 4px 0 var(--teal)}"
    ".livestatus{color:#aab;font-size:14px;margin-left:8px}input[type=color]{width:44px!important;height:30px;padding:0;"
    "border:0;background:none;vertical-align:middle}button.link{background:none;color:var(--teal);padding:2px 6px;font-weight:normal}"
    ".inline label{display:inline-block;margin:4px 10px 4px 0}.inline select,.inline input{width:auto!important}"
)

# The comfort script of every page (see the docstring: folding, live forms, drag to reorder). Plain browser
# JavaScript; pages mark what it should act on with classes / data- attributes and work without it.
SCRIPT = r"""
(()=>{
const holder=document.querySelector('[data-foldkey]');
const K='fold:'+location.pathname+':'+(holder?holder.dataset.foldkey:'');
const load=()=>{try{return JSON.parse(sessionStorage.getItem(K)||'{}')}catch(e){return {}}};
const keep=(id,v)=>{try{const m=load();m[id]=v;sessionStorage.setItem(K,JSON.stringify(m))}catch(e){}};
const target=location.hash.slice(1);
function cards(root){                       // details.card: open / closed as last left; the #anchor one opens
  const m=load();
  root.querySelectorAll('details.card[id]').forEach(d=>{
    if(d.id in m)d.open=m[d.id];
    if(target&&target===d.id)d.open=true;
    d.addEventListener('toggle',()=>keep(d.id,d.open));
  });
}
function clearMarks(){document.querySelectorAll('.dropbefore,.dropafter').forEach(x=>x.classList.remove('dropbefore','dropafter'))}
let dragged=null;
function drags(root){                       // [data-draglist] > details[id]: drag by the summary
  const lists=[...root.querySelectorAll('[data-draglist]')];
  if(root.matches&&root.matches('[data-draglist]'))lists.push(root);
  lists.forEach(list=>{
    [...list.children].filter(d=>d.matches('details[id]')).forEach(d=>{
      const s=d.querySelector(':scope>summary');
      s.draggable=true;
      s.addEventListener('dragstart',e=>{dragged=d;e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',d.id);d.classList.add('dragging')});
      s.addEventListener('dragend',()=>{d.classList.remove('dragging');clearMarks();dragged=null});
      d.addEventListener('dragover',e=>{
        if(!dragged||dragged===d||dragged.parentNode!==list)return;
        e.preventDefault();
        const r=d.getBoundingClientRect();clearMarks();
        d.classList.add(e.clientY>r.top+r.height/2?'dropafter':'dropbefore');
      });
      d.addEventListener('drop',e=>{
        if(!dragged||dragged===d||dragged.parentNode!==list)return;
        e.preventDefault();
        list.insertBefore(dragged,d.classList.contains('dropafter')?d.nextSibling:d);clearMarks();
        const form=list.closest('form');
        if(form&&form.elements.order){
          form.elements.order.value=[...list.children].filter(x=>x.matches('details[id]')).map(x=>x.id).join(',');
          if(form._send)form._send('order',true);else{const b=document.createElement('input');b.type='hidden';b.name='action';b.value='order';form.appendChild(b);form.submit()}
        }
      });
    });
  });
}
function wire(root){cards(root);drags(root)}
document.querySelectorAll('.main>section,.main>form>section').forEach((s,i)=>{   // sections fold on their h2
  const h=s.querySelector(':scope>h2');
  if(!h)return;
  const id='sec:'+(s.id||i);
  if(load()[id]&&target!==s.id)s.classList.add('folded');
  h.classList.add('foldh');
  h.addEventListener('click',e=>{if(e.target.closest('a,button,input,select'))return;keep(id,s.classList.toggle('folded'))});
});
document.querySelectorAll('form[data-live]').forEach(form=>{                    // forms that save themselves
  let chain=Promise.resolve(),seq=0,timer=0;
  const status=t=>{const s=form.querySelector('.livestatus');if(s)s.textContent=t};
  function send(action,rebuild){             // form.action would be the buttons named "action": read the attribute
    const my=++seq,data=new URLSearchParams(new FormData(form));
    data.set('action',action);status('saving…');
    chain=chain.then(()=>fetch(form.getAttribute('action'),{method:'POST',body:data})).then(r=>{if(!r.ok)throw 0;return r.text()}).then(html=>{
      if(my!==seq)return;                    // a newer change is already on its way
      const doc=new DOMParser().parseFromString(html,'text/html');
      const act=document.activeElement,name=act&&form.contains(act)?act.name:'';
      document.querySelectorAll('[data-swap]').forEach(el=>{
        if(el.dataset.swap==='rebuild'&&!rebuild)return;
        const src=doc.querySelector('[data-swap-id="'+el.dataset.swapId+'"]');
        if(src&&src.innerHTML!==el.innerHTML){el.innerHTML=src.innerHTML;wire(el)}
      });
      const again=name&&form.elements[name];
      if(rebuild&&again&&again.focus&&document.activeElement!==again)again.focus();
      status('saved ✓');
    }).catch(()=>status('could not save; press Save'));
  }
  form._send=send;
  const quick='select,input[type=checkbox],input[type=radio]';
  form.addEventListener('change',e=>{
    const t=e.target;
    if(!t.name||t.closest('[data-nolive]'))return;
    clearTimeout(timer);send('save',t.matches(quick)||t.type==='color');
  });
  form.addEventListener('input',e=>{
    const t=e.target;
    if(!t.name||t.closest('[data-nolive]')||t.matches(quick))return;
    clearTimeout(timer);timer=setTimeout(()=>send('save',false),700);
  });
});
document.querySelectorAll('[data-foldall]').forEach(b=>b.addEventListener('click',e=>{   // "Fold all" / "Open all"
  e.preventDefault();
  document.querySelectorAll('details.card').forEach(d=>{d.open=b.dataset.foldall==='open'});
}));
wire(document);
})();
"""


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
            f"<div class=main>{tabs}<h1>{_e(heading)}</h1>{note}{body}</div><script>{SCRIPT}</script></body></html>")
