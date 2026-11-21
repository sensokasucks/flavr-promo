"""Go-live cards posted as the host (flavrpromo/host_webhooks.py, bot.py post_start / _edit): the card
comes from the host's channel webhook without the "☕ **Name:**" part and the card's author line, its
edits go through the same webhook, the webhook is found again after a restart, its avatar follows a
new face picture, and without Manage Webhooks (or with the setting off) the bot posts it as before."""

from types import SimpleNamespace

import discord

from flavrpromo import config, groups, host_webhooks, hosts
from flavrpromo.bot import PromoBot
from flavrpromo.pings import Pinger
from flavrpromo.store import Store
from flavrpromo.watcher import Watcher

ME = SimpleNamespace(id=999)


class FakeMsg:
    def __init__(self, mid, author, kw, channel, webhook_id=None):
        self.id, self.author, self.kw, self.edits = mid, author, kw, []
        self.channel, self.webhook_id = channel, webhook_id
        self.embeds = [kw["embed"]]

    async def edit(self, **kw):
        self.edits.append(kw)


class FakeHook:
    """A discord.Webhook stand-in: send / edit_message land on the channel's messages."""

    def __init__(self, hid, name, channel, avatar):
        self.id, self.name, self.channel, self.avatars = hid, name, channel, [avatar]
        self.user, self.token = ME, "tok"

    async def send(self, **kw):
        m = FakeMsg(len(self.channel.msgs) + 1, SimpleNamespace(id=self.id), kw, self.channel, webhook_id=self.id)
        self.channel.msgs[m.id] = m
        return m

    async def edit_message(self, mid, **kw):
        self.channel.msgs[mid].edits.append(kw)

    async def edit(self, avatar=None, reason=None):
        self.avatars.append(avatar)


class FakeChannel:
    def __init__(self, cid, perm=True):
        self.id, self.msgs, self.hooks, self.perm, self.made = cid, {}, [], perm, 0

    async def send(self, **kw):
        m = FakeMsg(len(self.msgs) + 1, ME, kw, self)
        self.msgs[m.id] = m
        return m

    async def fetch_message(self, mid):
        return self.msgs[mid]

    async def webhooks(self):
        if not self.perm:
            raise discord.Forbidden(SimpleNamespace(status=403, reason="no"), "Missing Permissions")
        return list(self.hooks)

    async def create_webhook(self, name, avatar=None, reason=None):
        self.made += 1
        wh = FakeHook(500 + len(self.hooks), name, self, avatar)
        self.hooks.append(wh)
        return wh


def world(monkeypatch, tmp_path, perm=True):
    hosts.init(tmp_path, defaults=False)
    (tmp_path / "colette").mkdir(parents=True, exist_ok=True)
    (tmp_path / "colette" / "head.png").write_bytes(b"\x89PNG one")
    store = Store(":memory:")
    groups.init(store)
    bot = PromoBot(config.load({"DISCORD_TOKEN": "t", "OWNER_ID": "1"}), store, Pinger(store, None), Watcher(store, {}, {}))
    monkeypatch.setattr(type(bot), "user", property(lambda self: ME))
    ch = FakeChannel(55, perm)
    monkeypatch.setattr(bot, "get_channel", lambda cid: ch if cid == 55 else None)
    bot.host_hooks = host_webhooks.HostWebhooks(bot, store)
    store.put("live_channel.flavr", "55")
    store.put("hosts_on", True)
    store.put("hosts_only", "colette")
    lulu = store.add_person("Lulu", "flavr")
    person = {"id": lulu, "name": "Lulu", "grp": "flavr"}
    sid = store.start_session(lulu, 1_700_000_000, platforms=["twitch"], title="hi")
    store.segment_add(sid, lulu, "Valheim", 1_700_000_000, "new")
    live = {"twitch": {"url": "https://twitch.tv/lulu", "game": "Valheim"}}
    session = {"id": sid, "started_at": 1_700_000_000, "title": "hi"}
    return store, bot, ch, person, session, live


async def test_card_posted_and_edited_as_the_host(monkeypatch, tmp_path):
    store, bot, ch, person, session, live = world(monkeypatch, tmp_path)
    try:
        channel, message = await bot.post_start(person, session, live)
        msg = ch.msgs[int(message)]
        assert msg.webhook_id == ch.hooks[0].id and ch.hooks[0].name == "Colette Cappuccino"
        assert ch.hooks[0].avatars == [b"\x89PNG one"]                  # PNG face used as it is
        assert "Valheim" in msg.kw["content"] and not msg.kw["content"].startswith("☕")
        assert not msg.kw["embed"].author.name                          # the post itself shows who speaks
        assert msg.kw["allowed_mentions"].everyone is False
        # the end edit goes through the webhook, without the speaker part or an author line
        row = {**session, "host": "colette", "host_game": "Valheim", "post_channel": channel,
               "post_message": message, "ended_at": session["started_at"] + 3600}
        bot.host_hooks = host_webhooks.HostWebhooks(bot, store)        # a restart: found again by name
        await bot.post_end(person, row)
        end = msg.edits[-1]
        assert not end["content"].startswith("☕") and "1 h 0 min" in end["content"]
        assert not end["embed"].author.name and end["embed"].title == "Lulu was live"
        assert ch.made == 1
    finally:
        hosts.init(None)
        await bot.close()


async def test_new_face_updates_the_avatar(monkeypatch, tmp_path):
    store, bot, ch, person, session, live = world(monkeypatch, tmp_path)
    try:
        await bot.host_hooks.get(ch, "colette")
        assert ch.hooks[0].avatars == [b"\x89PNG one"]
        await bot.host_hooks.get(ch, "colette")                         # same face: no edit
        assert len(ch.hooks[0].avatars) == 1
        (tmp_path / "colette" / "head.png").write_bytes(b"\x89PNG two, a longer file")
        await bot.host_hooks.get(ch, "colette")
        assert ch.hooks[0].avatars[-1] == b"\x89PNG two, a longer file" and ch.made == 1
    finally:
        hosts.init(None)
        await bot.close()


async def test_no_permission_or_setting_off_posts_as_the_bot(monkeypatch, tmp_path):
    store, bot, ch, person, session, live = world(monkeypatch, tmp_path, perm=False)
    try:
        _, message = await bot.post_start(person, session, live)
        msg = ch.msgs[int(message)]
        assert msg.webhook_id is None and msg.kw["content"].startswith("☕ **Colette Cappuccino:**")
        assert msg.kw["embed"].author.name == "Colette Cappuccino · Marketing"
        assert bot.host_hooks._no_perm[55]                              # not asked again until a restart
        ch.perm = True
        store.put(host_webhooks.SETTING, False)                         # settings page box unticked
        _, message = await bot.post_start(person, session, live)
        assert ch.msgs[int(message)].webhook_id is None and ch.made == 0
    finally:
        hosts.init(None)
        await bot.close()


def test_unprefix_and_enabled():
    store = Store(":memory:")
    assert not host_webhooks.enabled(store)                             # hosts off
    store.put("hosts_on", True)
    assert host_webhooks.enabled(store)                                 # default on
    store.put(host_webhooks.SETTING, False)
    assert not host_webhooks.enabled(store)
    said = f"{hosts.speaker('clark')} Lulu is live."
    assert PromoBot._unprefix(said) == "Lulu is live." and PromoBot._unprefix("plain") == "plain"
    assert PromoBot._unprefix(None) is None


async def test_webp_face_drawn_to_png(tmp_path):
    # Discord avatars take PNG / JPEG only: a WebP face goes through Chromium on the host's colour
    hosts.init(tmp_path, defaults=False)
    (tmp_path / "clark").mkdir(parents=True, exist_ok=True)
    (tmp_path / "clark" / "head.webp").write_bytes(b"RIFFxxxxWEBP")
    seen = {}

    class Shooter:
        async def png(self, doc, size):
            seen["doc"], seen["size"] = doc, size
            return b"\x89PNG drawn"
    try:
        hooks = host_webhooks.HostWebhooks(SimpleNamespace(user=ME), Store(":memory:"), Shooter())
        assert await hooks.avatar("clark") == b"\x89PNG drawn"
        assert seen["size"] == (256, 256) and hosts.HOSTS["clark"]["accent"] in seen["doc"]
        assert await hooks.avatar("colette") is None                    # no face at all
    finally:
        hosts.init(None)
