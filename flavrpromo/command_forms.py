"""
Every slash command as a form: http://<this PC>:3871/settings/commands (owner 2026-11-21: "can we
add forms for all the discord commands onto that page as well?").

The forms are made from the bot's own command list (flavrpromo/bot.py, talent.py and promo.py
register them on bot.tree), so a new command or option shows up here by itself:
  text / whole number / number   a box (whole numbers keep the command's min and max)
  a fixed list (choices)         a drop-down
  yes / no                       a drop-down (optional ones can be left out)
  typed with suggestions         a box with the suggestions the command gives in Discord
                                 (its autocomplete, asked with an empty start)
  channel / role                 a drop-down of the server's text channels / roles (needs Discord
                                 connected); user: their Discord id (right-click → Copy User ID)
  file                           a file box (/host picture)
"Run" calls the command the way Discord would, as the owner (OWNER_ID), so the owner-only and
Manage Server checks pass, from no channel (talent-channel commands act like they do in an
ordinary channel; /me acts on the person linked to the owner). Its answer (text, embeds and
pictures) is shown on the page instead of in Discord; what a command posts in a channel (like
/calendar post) still goes to that channel. The message menu entries (community calendar) need a
Discord message, so they stay in Discord.

No password, like the rest of port 3871 (home network only; never forward the port).
Who calls it: flavrpromo/__main__.py (``add_routes`` on the web server, with poster.discord = the bot).
"""

from __future__ import annotations

import html
import inspect
import logging
import re
import time
import traceback
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import discord
from aiohttp import web
from discord import app_commands
from discord.enums import AppCommandOptionType as T

from .settings_page import _e, frame

log = logging.getLogger("flavrpromo.command_forms")
KEEP = 20                   # answers kept in memory for the page (newest first; gone on restart)
_results: Dict[str, Dict[str, Any]] = {}


# ── a stand-in for Discord's interaction ─────────────────────────────────
class _Sent:
    """What a command sent: collects send_message / followup.send calls for the page."""

    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []

    def add(self, content: Any = None, **kw: Any) -> None:
        files = list(kw.get("files") or []) + ([kw["file"]] if kw.get("file") else [])
        embeds = list(kw.get("embeds") or []) + ([kw["embed"]] if kw.get("embed") else [])
        out = []
        for f in files:
            fp = getattr(f, "fp", None)
            try:
                fp.seek(0)
                data = fp.read()
            except Exception:
                data = b""
            out.append((str(getattr(f, "filename", "file")), data))
        self.messages.append({"text": "" if content is None else str(content),
                              "embeds": [e.to_dict() for e in embeds], "files": out,
                              "ephemeral": bool(kw.get("ephemeral"))})


class _Response:
    def __init__(self, sent: _Sent) -> None:
        self._sent, self._done = sent, False

    async def send_message(self, content: Any = None, **kw: Any) -> None:
        self._done = True
        self._sent.add(content, **kw)

    async def defer(self, **kw: Any) -> None:
        self._done = True

    def is_done(self) -> bool:
        return self._done

    async def send_modal(self, modal: Any) -> None:
        self._done = True
        self._sent.add("This command opens a form in Discord; use it there.")


class _Followup:
    def __init__(self, sent: _Sent) -> None:
        self._sent = sent

    async def send(self, content: Any = None, **kw: Any) -> None:
        self._sent.add(content, **kw)


class PageInteraction:
    """Just the parts of discord.Interaction the commands use (inter.user, inter.channel_id,
    inter.response, inter.followup; checked by grep over flavrpromo/ 2026-11-21). The user is the
    owner, with Manage Server, so bot.is_owner_id and bot.may_manage pass."""

    def __init__(self, bot: Any) -> None:
        owner = int(bot.settings.owner_id)
        self.client = bot
        self.user = SimpleNamespace(id=owner, name="owner", display_name="owner", mention=f"<@{owner}>",
                                    guild_permissions=SimpleNamespace(manage_guild=True, administrator=True), bot=False)
        self.channel_id: Optional[int] = None
        self.channel = None
        self.guild_id = getattr(bot.settings, "guild_id", None) or None
        self.guild = bot.get_guild(int(self.guild_id)) if self.guild_id and hasattr(bot, "get_guild") else None
        self.sent = _Sent()
        self.response = _Response(self.sent)
        self.followup = _Followup(self.sent)


class PageAttachment:
    """A file from the page's file box, shaped like discord.Attachment for /host picture."""

    def __init__(self, filename: str, data: bytes, content_type: str = "") -> None:
        self.filename, self._data, self.content_type = filename, data, content_type
        self.size = len(data)

    async def read(self) -> bytes:
        return self._data


# ── the commands ─────────────────────────────────────────────────────────
def commands(bot: Any) -> List[app_commands.Command]:
    """Every slash command (groups walked), in the order Discord shows them."""
    out = [c for c in bot.tree.walk_commands() if isinstance(c, app_commands.Command)]
    return sorted(out, key=lambda c: c.qualified_name)


def _find(bot: Any, name: str) -> Optional[app_commands.Command]:
    return next((c for c in commands(bot) if c.qualified_name == name), None)


def _wants_choice(cmd: app_commands.Command, name: str) -> bool:
    """True when the command's option is typed app_commands.Choice[...] (it gets the Choice, not
    just its value; the bot's files use ``from __future__ import annotations``, so it's a string)."""
    try:
        return "Choice" in str(inspect.signature(cmd.callback).parameters[name].annotation)
    except (KeyError, ValueError, TypeError):
        return False


def _guilds(bot: Any) -> List[Any]:
    try:
        return list(bot.guilds)
    except Exception:
        return []


def _channels(bot: Any) -> List[Tuple[int, str]]:
    out = []
    for g in _guilds(bot):
        for ch in g.text_channels:
            out.append((ch.id, f"#{ch.name}" + (f" ({g.name})" if len(_guilds(bot)) > 1 else "")))
    return out


def _roles(bot: Any) -> List[Tuple[int, str]]:
    return [(r.id, f"@{r.name}") for g in _guilds(bot) for r in g.roles if not r.is_default()]


async def _suggestions(bot: Any, cmd: app_commands.Command, name: str) -> List[Any]:
    """The option's autocomplete answers for an empty start ([] when it has none or fails)."""
    cb = getattr(cmd._params.get(name), "autocomplete", None)
    if cb is None:
        return []
    try:
        got = await cb(PageInteraction(bot), "")
        return [c.value for c in got or []][:25]
    except Exception as e:
        log.debug("autocomplete %s %s: %s", cmd.qualified_name, name, e)
        return []


def _anchor(cmd: app_commands.Command) -> str:
    return "c-" + cmd.qualified_name.replace(" ", "-")


async def _field(bot: Any, cmd: app_commands.Command, p: Any) -> str:
    """One option's input."""
    n, req = p.name, p.required
    label = f'<b>{_e(n)}</b>{"" if req else " <small class=opt>(optional)</small>"}'
    hint = f"<small>{_e(p.description)}</small>" if p.description and p.description != "…" else ""
    r = " required" if req else ""
    if p.choices:
        opts = ("" if req else '<option value="">(leave out)</option>') + "".join(
            f'<option value="{_e(c.value)}">{_e(c.name)}</option>' for c in p.choices)
        box = f'<select name="{n}"{r}>{opts}</select>'
    elif p.type == T.boolean:
        box = (f'<select name="{n}">' + ("" if req else '<option value="">(leave out)</option>')
               + '<option value="1">yes</option><option value="0">no</option></select>')
    elif p.type in (T.integer, T.number):
        lim = "".join(f' {k}="{v}"' for k, v in (("min", p.min_value), ("max", p.max_value)) if v is not None)
        step = "" if p.type == T.integer else ' step="any"'
        box = f'<input type=number name="{n}"{lim}{step}{r}>'
    elif p.type == T.channel:
        chans = _channels(bot)
        box = (f'<select name="{n}"{r}>' + ("" if req else '<option value="">(leave out)</option>')
               + "".join(f'<option value="{i}">{_e(t)}</option>' for i, t in chans) + "</select>") if chans else \
            f'<input name="{n}" placeholder="channel id (Discord isn\'t connected)"{r}>'
    elif p.type == T.role:
        roles = _roles(bot)
        box = (f'<select name="{n}"{r}>' + ("" if req else '<option value="">(leave out)</option>')
               + "".join(f'<option value="{i}">{_e(t)}</option>' for i, t in roles) + "</select>") if roles else \
            f'<input name="{n}" placeholder="role id (Discord isn\'t connected)"{r}>'
    elif p.type in (T.user, T.mentionable):
        box = f'<input name="{n}" inputmode=numeric placeholder="their Discord id (right-click them → Copy User ID)"{r}>'
    elif p.type == T.attachment:
        box = f'<input type=file name="{n}"{r}>'
    else:
        sug = await _suggestions(bot, cmd, n)
        lid = f"{_anchor(cmd)}-{n}"
        dl = (f'<datalist id="{lid}">' + "".join(f'<option value="{_e(v)}">' for v in sug) + "</datalist>") if sug else ""
        lim = f' maxlength="{p.max_value}"' if p.max_value else ""
        box = f'<input name="{n}"{" list=" + chr(34) + lid + chr(34) if sug else ""}{lim}{r}>{dl}'
    return f"<label>{label}{hint}{box}</label>"


async def _convert(bot: Any, cmd: app_commands.Command, form: Any) -> Tuple[Dict[str, Any], List[str]]:
    """The form's values as the command's arguments (left-out optional ones are not passed, so the
    command's own default applies) and any problems."""
    args: Dict[str, Any] = {}
    bad: List[str] = []
    for p in cmd.parameters:
        n = p.name
        raw = form.get(n)
        if p.type == T.attachment:
            if isinstance(raw, web.FileField) and raw.filename:
                args[n] = PageAttachment(raw.filename, raw.file.read(), raw.content_type or "")
            elif p.required:
                bad.append(f"{n}: pick a file")
            continue
        text = str(raw or "").strip()
        if not text:
            if p.required:
                bad.append(f"{n}: needed")
            continue
        try:
            if p.choices:
                ch = next((c for c in p.choices if str(c.value) == text), None)
                if ch is None:
                    raise ValueError("not one of the choices")
                args[n] = ch if _wants_choice(cmd, n) else ch.value
            elif p.type == T.boolean:
                args[n] = text in ("1", "yes", "true", "on")
            elif p.type in (T.integer, T.number):
                v = int(text) if p.type == T.integer else float(text)
                if (p.min_value is not None and v < p.min_value) or (p.max_value is not None and v > p.max_value):
                    raise ValueError(f"between {p.min_value} and {p.max_value}")
                args[n] = v
            elif p.type == T.channel:
                ch = bot.get_channel(int(text))
                if ch is None:
                    raise ValueError("no such channel (is Discord connected?)")
                args[n] = ch
            elif p.type == T.role:
                role = next((r for g in _guilds(bot) for r in g.roles if r.id == int(text)), None)
                if role is None:
                    raise ValueError("no such role (is Discord connected?)")
                args[n] = role
            elif p.type in (T.user, T.mentionable):
                uid = int(text)
                args[n] = bot.get_user(uid) or await bot.fetch_user(uid)
            else:
                if p.max_value and len(text) > p.max_value:
                    raise ValueError(f"at most {p.max_value} characters")
                args[n] = text
        except (ValueError, discord.HTTPException) as e:
            bad.append(f"{n}: {e}")
    return args, bad


async def run(bot: Any, name: str, form: Any) -> Dict[str, Any]:
    """Run one command from the page; the answer as {"cmd", "args", "messages", "error"}."""
    cmd = _find(bot, name)
    out: Dict[str, Any] = {"cmd": name, "args": {}, "messages": [], "error": "", "at": time.time()}
    if cmd is None:
        out["error"] = "No such command."
        return out
    args, bad = await _convert(bot, cmd, form)
    out["args"] = {k: (getattr(v, "name", None) or getattr(v, "filename", None) or v) for k, v in args.items()}
    if bad:
        out["error"] = "Not run: " + "; ".join(bad)
        return out
    inter = PageInteraction(bot)
    try:
        await cmd.callback(inter, **args)
    except Exception as e:
        log.warning("page command /%s failed: %s", name, e)
        out["error"] = f"The command failed: {e.__class__.__name__}: {e}\n" + "".join(traceback.format_exc(limit=3))[-1500:]
    out["messages"] = inter.sent.messages
    if not out["messages"] and not out["error"]:
        out["messages"] = [{"text": "(Done; the command sent no answer.)", "embeds": [], "files": [], "ephemeral": True}]
    return out


def _keep(result: Dict[str, Any]) -> str:
    rid = f"{int(time.time() * 1000):x}"
    _results[rid] = result
    for old in sorted(_results)[:-KEEP]:
        _results.pop(old, None)
    return rid


# ── showing an answer ─────────────────────────────────────────────────────
def md(text: str) -> str:
    """Discord's markdown, roughly, as HTML: **bold**, *italic*, __underline__, ~~strike~~, `code`,
    [links](url), <t:unix:style> times (in this PC's time zone), new lines. Escaped first."""
    s = html.escape(text or "")
    s = re.sub(r"&lt;t:(\d+)(?::\w)?&gt;", lambda m: datetime.fromtimestamp(int(m.group(1))).strftime("%a %b %d, %I:%M %p"), s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target=_blank>\1</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__(.+?)__", r"<u>\1</u>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", s)
    s = re.sub(r"~~(.+?)~~", r"<s>\1</s>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s.replace("\n", "<br>")


def answer_html(rid: str, r: Dict[str, Any]) -> str:
    args = " ".join(f"{k}:{v}" for k, v in r["args"].items())
    parts = [f'<div class=answer><p><b>/{_e(r["cmd"])}</b> {_e(args)}</p>']
    if r.get("error"):
        parts.append(f'<pre class=err>{_e(r["error"])}</pre>')
    for mi, m in enumerate(r["messages"]):
        files = {name: fi for fi, (name, _) in enumerate(m["files"])}
        bits = [f'<div class=msg>{md(m["text"])}' if m["text"] else "<div class=msg>"]
        for e in m["embeds"]:
            col = f'#{int(e.get("color") or 0x2ae0d4):06x}'
            fields = "".join(f'<div class=f><b>{md(f.get("name", ""))}</b><div>{md(f.get("value", ""))}</div></div>'
                             for f in e.get("fields") or [])
            img = (e.get("image") or {}).get("url") or ""
            if img.startswith("attachment://") and img[13:] in files:
                img = f"/settings/commands/file/{rid}/{mi}/{files.pop(img[13:])}"
            title = md(e.get("title", ""))
            if e.get("url"):
                title = f'<a href="{_e(e["url"])}" target=_blank>{title}</a>'
            bits.append(f'<div class=embed style="border-color:{col}"><b>{title}</b>'
                        f'<div>{md(e.get("description", ""))}</div>{fields}'
                        + (f'<img src="{_e(img)}" alt="">' if img else "")
                        + (f'<small>{md((e.get("footer") or {}).get("text", ""))}</small>' if e.get("footer") else "")
                        + "</div>")
        for name, fi in files.items():
            url = f"/settings/commands/file/{rid}/{mi}/{fi}"
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                bits.append(f'<img src="{url}" alt="{_e(name)}">')
            bits.append(f'<p><a href="{url}" download="{_e(name)}">Save {_e(name)}</a></p>')
        parts.append("".join(bits) + "</div>")
    return "".join(parts) + "</div>"


async def page(bot: Any, rid: str = "", saved: str = "") -> str:
    shown = _results.get(rid)
    blocks: Dict[str, List[str]] = {}
    for cmd in commands(bot):
        fields = "".join([await _field(bot, cmd, p) for p in cmd.parameters])
        opened = " open" if shown and shown["cmd"] == cmd.qualified_name else ""
        ans = answer_html(rid, shown) if opened else ""
        blocks.setdefault(cmd.qualified_name.split()[0], []).append(
            f'<details id="{_anchor(cmd)}"{opened}><summary><b>/{_e(cmd.qualified_name)}</b> '
            f'<small class=d>{_e(cmd.description)}</small></summary>'
            f'<form method=post action=/settings/commands enctype=multipart/form-data>'
            f'<input type=hidden name=__cmd value="{_e(cmd.qualified_name)}">{fields or "<p class=help>No options.</p>"}'
            f'<p><button>Run /{_e(cmd.qualified_name)}</button></p></form>{ans}</details>')
    nav = " · ".join(f'<a href="#g-{g}">/{_e(g)}</a>' for g in blocks)
    body = ('<p class=help>Every slash command, run as you (the owner) from no channel. The answer shows here '
            'instead of in Discord; anything a command posts in a channel (like /calendar post) still goes there. '
            'The message menu (Add to community calendar) stays in Discord.'
            + ("" if _guilds(bot) else " <b>Discord isn't connected right now</b>, so channels and roles are typed as ids.")
            + f'</p><nav class=in>{nav}</nav>'
            + "".join(f'<section id="g-{g}"><h2>/{_e(g)}</h2>{"".join(b)}</section>' for g, b in blocks.items()))
    style = ("details{border:1px solid #444;border-radius:8px;margin:6px 0;padding:6px 12px}summary{cursor:pointer}"
             ".d{display:inline;color:#aab}.opt{display:inline}.answer{background:#0e0f14;border-radius:8px;padding:10px;"
             "margin:8px 0}.msg{margin:8px 0}.embed{border-left:5px solid;background:#22232b;padding:8px 12px;"
             "border-radius:6px;margin:6px 0}.embed .f{margin-top:6px}.embed img,.msg img{max-width:100%;border-radius:6px;"
             "margin-top:6px}.err{color:#ff9aa8}code{background:#333;padding:0 4px;border-radius:4px}")
    return frame("Commands", "⌨️ Commands", body, saved, style)


def add_routes(app: web.Application, poster: Any) -> None:
    async def get(request: web.Request) -> web.Response:
        return web.Response(text=await page(poster.discord, request.query.get("r", ""), request.query.get("saved", "")),
                            content_type="text/html")

    async def post(request: web.Request) -> web.Response:
        form = await request.post()
        name = str(form.get("__cmd") or "")
        result = await run(poster.discord, name, form)
        rid = _keep(result)
        cmd = _find(poster.discord, name)
        raise web.HTTPSeeOther(f"/settings/commands?r={rid}" + (f"#{_anchor(cmd)}" if cmd else ""))

    async def file(request: web.Request) -> web.Response:
        r = _results.get(request.match_info["rid"])
        try:
            name, data = r["messages"][int(request.match_info["m"])]["files"][int(request.match_info["f"])]
        except (TypeError, KeyError, IndexError, ValueError):
            raise web.HTTPNotFound()
        ctype = "image/png" if name.lower().endswith(".png") else "application/octet-stream"
        return web.Response(body=data, content_type=ctype, headers={"Cache-Control": "no-store"})

    app.router.add_get("/settings/commands", get)
    app.router.add_post("/settings/commands", post)
    app.router.add_get("/settings/commands/file/{rid}/{m}/{f}", file)


__all__ = ["add_routes", "run", "page", "commands", "PageInteraction", "md"]
