"""
Go-live cards posted as the host (owner 2026-11-21, plan doc "FlaVR Bot presenter plan": "live cards
posted via channel webhook as the host (name + head avatar)").

With hosts on (/host setup on) and "post as the host" on (kv hosts_webhook, default on; the settings
page's Hosts section), a go-live card comes from "Colette Cappuccino" or "Clark" with their face as
the avatar instead of from the bot. Discord does that with a channel webhook: this file makes one
per host per live channel (named after the host, their face as its avatar, made by the bot so only
the bot has its token) and finds it again after a restart. The card's later edits (game change,
stream end) go through the same webhook, because only the webhook that posted a message can edit it.

Needs the bot's Manage Webhooks permission in that channel. Without it (or on any Discord error)
the card is posted by the bot as before, with the host's line and face on the card: nothing is lost.

Avatars: Discord takes PNG / JPEG; the built-in faces are WebP, so a face is drawn onto a 256 x 256
square in the host's colour with Chromium (poster.shooter) when it isn't PNG / JPEG already. A new
face picture (/host picture, settings page) updates the webhook's avatar on its next post (the
face's size and time are kept in kv host_webhook_faces).

Who calls it: flavrpromo/bot.py (post_start, _edit). The webhooks themselves are cached in memory;
kv keeps nothing secret (Discord gives the token to the bot again when it lists the channel's webhooks).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import discord

from . import hosts

log = logging.getLogger("flavrpromo.host_webhooks")
SETTING = "hosts_webhook"           # kv: post go-live cards as the host (default on)
FACES = "host_webhook_faces"        # kv: {webhook id: face signature} (avatar up to date?)
AVATAR = 256                        # px; the square avatar drawn from a WebP face


def enabled(store: Any) -> bool:
    """Post go-live cards as the host? Only with hosts on, and the setting not switched off."""
    return hosts.enabled(store) and store.get(SETTING) is not False


def _sig(key: str) -> str:
    """The host's face picture as "path:size:mtime" ("" = no face): changes when a new one is uploaded."""
    face = hosts.face(key)
    if face is None:
        return ""
    st = face.stat()
    return f"{face}:{st.st_size}:{int(st.st_mtime)}"


class HostWebhooks:
    """The webhooks of the hosts in the live channels. ``bot``: the discord client (its user id tells
    our webhooks from others'); ``shooter``: render.Screenshotter or None (WebP faces → PNG)."""

    def __init__(self, bot: Any, store: Any, shooter: Any = None):
        self.bot, self.store, self.shooter = bot, store, shooter
        self._hooks: Dict[Tuple[int, str], discord.Webhook] = {}     # (channel id, host key) → webhook
        self._by_id: Dict[int, discord.Webhook] = {}
        self._no_perm: Dict[int, bool] = {}                           # channels where we may not (until restart)

    async def avatar(self, key: str) -> Optional[bytes]:
        """The host's face as PNG / JPEG bytes for a webhook avatar (None = no face)."""
        face = hosts.face(key)
        if face is None:
            return None
        data = face.read_bytes()
        if face.suffix.lower() in (".png", ".jpg", ".jpeg") or self.shooter is None:
            return data
        h = hosts.HOSTS[key]
        doc = (f"<!doctype html><html><body style='margin:0;width:{AVATAR}px;height:{AVATAR}px;background:{h['accent']};"
               f"display:flex;align-items:flex-end;justify-content:center;overflow:hidden'>"
               f"<img src='{hosts.data_url(key, face.stem)}' style='width:{AVATAR}px;height:{AVATAR}px;object-fit:cover;"
               f"object-position:top'></body></html>")
        try:
            return await self.shooter.png(doc, size=(AVATAR, AVATAR))
        except Exception as e:
            log.info("host avatar picture failed, using the file as it is: %s", e)
            return data

    def _ours(self, wh: Any) -> bool:
        me = getattr(self.bot, "user", None)
        return me is not None and getattr(getattr(wh, "user", None), "id", None) == me.id and bool(getattr(wh, "token", None))

    async def _load(self, channel: Any) -> None:
        """Find our webhooks in a channel (after a restart), by name."""
        names = {h["name"]: k for k, h in hosts.HOSTS.items()}
        for wh in await channel.webhooks():
            if self._ours(wh) and wh.name in names:
                self._hooks[(channel.id, names[wh.name])] = wh
                self._by_id[wh.id] = wh

    async def get(self, channel: Any, key: str) -> Optional[discord.Webhook]:
        """The host's webhook in this channel (made when missing; its avatar refreshed when the face
        changed). None = can't (no Manage Webhooks, a thread / DM, or Discord said no)."""
        if self._no_perm.get(channel.id) or not hasattr(channel, "webhooks"):
            return None
        try:
            if (channel.id, key) not in self._hooks:
                await self._load(channel)
            wh = self._hooks.get((channel.id, key))
            sig = _sig(key)
            if wh is None:
                wh = await channel.create_webhook(name=hosts.HOSTS[key]["name"], avatar=await self.avatar(key),
                                                  reason="FlaVR Promo: go-live cards posted as the host")
                self._hooks[(channel.id, key)] = wh
                self._by_id[wh.id] = wh
                self._remember(wh.id, sig)
            elif (self.store.get(FACES) or {}).get(str(wh.id)) != sig:
                await wh.edit(avatar=await self.avatar(key), reason="FlaVR Promo: the host's face changed")
                self._remember(wh.id, sig)
            return wh
        except discord.Forbidden:
            log.info("no Manage Webhooks in channel %s: go-live cards come from the bot there", channel.id)
            self._no_perm[channel.id] = True
            return None
        except discord.HTTPException as e:
            log.info("host webhook in %s failed: %s", channel.id, e)
            return None

    def _remember(self, wh_id: int, sig: str) -> None:
        faces = dict(self.store.get(FACES) or {})
        faces[str(wh_id)] = sig
        self.store.put(FACES, faces)

    async def owner_of(self, msg: Any) -> Optional[discord.Webhook]:
        """The webhook of ours that posted ``msg`` (None = not a webhook post, or not ours)."""
        wid = getattr(msg, "webhook_id", None)
        if not wid:
            return None
        if wid not in self._by_id:
            try:
                await self._load(msg.channel)
            except discord.HTTPException:
                return None
        return self._by_id.get(wid)
