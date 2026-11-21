"""
YouTube for the go-live watcher.

  * Each channel's public RSS feed (www.youtube.com/feeds/videos.xml?channel_id=...): its newest
    15 videos, including scheduled and live streams. Free, no key.
  * One Data API ``videos.list`` call (YOUTUBE_API_KEY, a free key from console.cloud.google.com;
    1 quota unit per call of up to 50 videos, 10,000 units a day) says which of those videos are
    live now or scheduled, with the real start time. The RSS "published" date is NOT the stream
    start (waiting rooms are made days ahead), so without a key YouTube streams aren't watched.
  * A handle (@name) is turned into a channel id with ``channels.list?forHandle=`` (1 unit, once).
    Without a key, add people by channel id (UC...) instead.

Past weeks (``past_streams``, for Watcher.backfill): the channel's uploads list
(playlistItems.list, 1 unit per 50 videos, newest first, stops at the week) and one videos.list for
their real start and end times. Finished livestreams are in the uploads list as long as the
streamer keeps the VOD public.

Community posts (``videos``, flavrpromo/promo.py): one videos.list per check for the streams members
added to the community calendar, to follow each from scheduled to live to finished.

Videos already known to be over are remembered (``_done``) and never asked about again.

Waiting rooms made long ahead (Sen 2026-11-20: Amanda's Nov 22 stream, made Oct 22, never showed):
the RSS feed lists only the 15 newest videos, so a waiting room drops out of it once the channel
posts 15 more. Three things catch those:
  * every upcoming stream found is remembered (``_upcoming_ids``) and asked about directly until it
    goes live, ends or is gone, even after it leaves the feed;
  * every UPLOADS_EVERY (6 h) per channel, its uploads list (playlistItems.list, the 50 newest
    videos, 1 quota unit) instead of the feed's 15; only videos not yet known are then asked about
    (videos.list, 1 unit per 50). Waiting rooms sit in that list like any video;
  * the deep check, OFF by default (owner 2026-11-20): one ``search.list`` per channel
    (eventType=upcoming, 100 quota units) for its scheduled streams wherever they are, every
    ``search_every`` seconds. The owner picks off / daily / every 48 h / weekly with
    /setup youtube-check (kv "youtube_deep_check", DEEP_CHECK below); flavrpromo/__main__.py and that
    command set ``search_every``. About 15 channels x 100 = 1,500 of the 10,000 free daily units a run.
    It runs at start-up too when on (the times are kept in memory only).
Premieres count as streams (YouTube calls a scheduled premiere "upcoming", then "live" while it
plays). Shorts, ordinary uploads and premieres are also passed on in ``new_uploads`` (the same
videos.list answer, no extra quota) for the reviews' "Also this week" list (flavrpromo/watcher.py
saves them): a Short is a vertical video (its player comes back taller than wide when asked with
maxWidth; owner's tip 2026-11-20) of SHORT_MAX seconds or less; a premiere is a scheduled video
that already has a length (a waiting live stream's length is 0), so it's caught while it waits.

Activity for the reviews (owner 2026-11-20: "leave the free ones be", but deep-check only people who
did something): every feed read also fills ``posted`` {channel id: [published unix s]} with the times
of the channel's recent videos (free). flavrpromo/watcher.py saves them (store.note_activity), and the
review's one-time deep check (Watcher.backfill → past_streams, the costly part) runs only for people
with a stream, upload or feed sighting in the review's days.
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import aiohttp

from . import UA, Live
from .twitch import chunks, iso_ts

log = logging.getLogger("flavrpromo.youtube")
API = "https://www.googleapis.com/youtube/v3"
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id="
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
CHANNEL_ID = re.compile(r"^UC[\w-]{22}$")
# Only feed videos this new are asked about. Waiting rooms are often made weeks ahead, so this
# is long; every video is asked about once and remembered (_done) once it's over or an upload.
FRESH_DAYS = 45
UPLOADS_EVERY = 6 * 3600.0      # per channel: its 50 newest uploads (1 quota unit) to find older waiting rooms
# the deep check's choices (/setup youtube-check, kv "youtube_deep_check"): label → seconds between
# runs per channel (0 = off, the default). One run = one search.list = 100 quota units per channel.
SHORT_MAX = 180.0               # seconds: YouTube Shorts are up to 3 minutes long (and vertical)
UPLOAD_FRESH = 8 * 86400.0      # only videos published this recently go in new_uploads (not a channel's whole past)
DEEP_CHECK = {"off": 0.0, "daily": 24 * 3600.0, "48h": 48 * 3600.0, "weekly": 7 * 24 * 3600.0}


def iso_length(text: str) -> float:
    """YouTube's ISO 8601 length ("PT1M5S", "PT2H", "P0D") → seconds."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", text or "")
    if not m:
        return 0.0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return float(((d * 24 + h) * 60 + mi) * 60 + se)


def upload_info(v: Dict[str, Any], now: float) -> Optional[Dict[str, Any]]:
    """One videos.list item → an "Also this week" entry, or None for a live stream / an old video.
    kind: "short" (vertical and SHORT_MAX s or less), "premiere" (scheduled, with a length already),
    else "video". Shape from the player size (asked with maxWidth); unknown shape = not a Short."""
    sn = v.get("snippet") or {}
    ld = v.get("liveStreamingDetails")
    length = iso_length(str((v.get("contentDetails") or {}).get("duration") or ""))
    vid = str(v.get("id") or "")
    if ld:
        # only a WAITING premiere can be told apart: it already has a length, a waiting live stream has
        # 0. Once played, a premiere looks like a finished stream (then its saved row keeps the label).
        if sn.get("liveBroadcastContent") != "upcoming" or length <= 0:
            return None
        kind, at = "premiere", iso_ts(str(ld.get("scheduledStartTime") or ""))
    else:
        pl = v.get("player") or {}
        w, h = int(pl.get("embedWidth") or 0), int(pl.get("embedHeight") or 0)
        kind = "short" if h > w > 0 and 0 < length <= SHORT_MAX else "video"
        at = iso_ts(str(sn.get("publishedAt") or ""))
    if not at or at < now - UPLOAD_FRESH:
        return None
    return {"video_id": vid, "kind": kind, "at": at, "title": str(sn.get("title") or ""),
            "url": f"https://www.youtube.com/{'shorts/' + vid if kind == 'short' else 'watch?v=' + vid}",
            "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", "length": length}


def parse_feed(xml_text: str) -> List[Dict[str, Any]]:
    """RSS → [{video_id, title, published (unix s), thumb}] newest first."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", "", NS)
        if not vid:
            continue
        thumb = e.find("media:group/media:thumbnail", NS)
        out.append({"video_id": vid, "title": e.findtext("a:title", "", NS),
                    "published": iso_ts(e.findtext("a:published", "", NS)) or 0.0,
                    "thumb": thumb.get("url") if thumb is not None else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"})
    return out


class YouTube:
    platform = "youtube"

    def __init__(self, http: aiohttp.ClientSession, api_key: str = ""):
        self.http = http
        self.api_key = api_key
        self._done: set[str] = set()          # videos known to be over or plain uploads
        self.upcoming: Dict[str, List[Dict[str, Any]]] = {}   # channel id → scheduled streams (for /schedule)
        self._upcoming_ids: Dict[str, str] = {}   # video id → channel id: waiting rooms seen, asked until they start
        self._searched: Dict[str, float] = {}     # channel id → last search.list for its upcoming streams
        self._scanned: Dict[str, float] = {}      # channel id → last read of its uploads list
        self.search_every = 0.0                   # the deep check: seconds between runs, 0 = off (DEEP_CHECK)
        self.posted: Dict[str, List[float]] = {}  # last check: channel id → its feed videos' publish times (activity)
        # channel id → videos that aren't streams seen in the last live() (flavrpromo/watcher.py saves them):
        # [{video_id, kind ("video" / "short" / "premiere"), at, title, url, thumb, length}]
        self.new_uploads: Dict[str, List[Dict[str, Any]]] = {}

    @property
    def ready(self) -> bool:
        return bool(self.api_key)

    async def _api(self, path: str, params: Dict[str, str]) -> Dict[str, Any]:
        async with self.http.get(API + path, params={**params, "key": self.api_key},
                                 headers={"User-Agent": UA}) as r:
            if r.status != 200:
                raise RuntimeError(f"YouTube {path} answered HTTP {r.status} (check YOUTUBE_API_KEY and its quota)")
            return await r.json(content_type=None)

    async def resolve(self, handles: List[str]) -> Dict[str, Optional[Dict[str, str]]]:
        out: Dict[str, Optional[Dict[str, str]]] = {}
        for h in handles:
            out[h] = None
            if CHANNEL_ID.match(h):
                out[h] = {"platform_id": h, "display": "", "avatar": ""}
                if not self.api_key:
                    continue
                params = {"part": "snippet", "id": h}
            elif self.api_key:
                params = {"part": "snippet", "forHandle": h if h.startswith("@") else "@" + h}
            else:
                continue
            try:
                items = (await self._api("/channels", params)).get("items") or []
            except RuntimeError as e:
                log.warning("%s", e)
                continue
            if items:
                sn = items[0].get("snippet") or {}
                out[h] = {"platform_id": str(items[0].get("id") or ""), "display": str(sn.get("title") or ""),
                          "avatar": str(((sn.get("thumbnails") or {}).get("default") or {}).get("url") or "")}
        return out

    async def feed(self, channel_id: str) -> List[Dict[str, Any]]:
        async with self.http.get(FEED + channel_id, headers={"User-Agent": UA}) as r:
            if r.status != 200:
                return []
            return parse_feed(await r.text())

    async def newest_uploads(self, channel_id: str) -> List[str]:
        """The channel's 50 newest videos from its uploads list (its id with UC → UU; 1 quota unit):
        video ids. Waiting rooms and premieres are in it like any other video."""
        data = await self._api("/playlistItems", {"part": "contentDetails", "playlistId": "UU" + channel_id[2:],
                                                  "maxResults": "50"})
        return [str((i.get("contentDetails") or {}).get("videoId") or "") for i in data.get("items") or []
                if (i.get("contentDetails") or {}).get("videoId")]

    async def search_upcoming(self, channel_id: str) -> List[str]:
        """The channel's scheduled streams straight from YouTube's search (100 quota units): video ids."""
        data = await self._api("/search", {"part": "id", "channelId": channel_id, "eventType": "upcoming",
                                           "type": "video", "maxResults": "25"})
        return [str((i.get("id") or {}).get("videoId") or "") for i in data.get("items") or []
                if (i.get("id") or {}).get("videoId")]

    async def live(self, accounts: List[Dict[str, Any]]) -> Dict[str, Live]:
        """RSS for every channel (plus its uploads list every UPLOADS_EVERY, the deep check when it's on,
        and the waiting rooms already found), then one videos.list per 50 of the fresh, not-yet-finished
        videos."""
        if not self.api_key:
            return {}
        owner_of: Dict[str, str] = {}
        now = time.time()
        cutoff = now - FRESH_DAYS * 86400
        followed = {a.get("platform_id") or "" for a in accounts} - {""}
        self.posted = {}
        for a in accounts:
            cid = a.get("platform_id") or ""
            if not cid:
                continue
            try:
                entries = await self.feed(cid)
                self.posted[cid] = [v["published"] for v in entries if v["published"] >= cutoff]
                for v in entries:
                    if v["video_id"] not in self._done and v["published"] >= cutoff:
                        owner_of[v["video_id"]] = cid
            except aiohttp.ClientError as e:
                log.info("YouTube feed for %s failed: %s", cid, e)
            if now - self._scanned.get(cid, 0.0) >= UPLOADS_EVERY and CHANNEL_ID.match(cid):
                self._scanned[cid] = now
                try:
                    for vid in await self.newest_uploads(cid):
                        if vid not in self._done:
                            owner_of.setdefault(vid, cid)
                except (aiohttp.ClientError, RuntimeError) as e:
                    log.info("YouTube uploads list for %s failed: %s", cid, e)
            if self.search_every and now - self._searched.get(cid, 0.0) >= self.search_every:
                self._searched[cid] = now           # also on failure: a quota problem shouldn't retry every check
                try:
                    for vid in await self.search_upcoming(cid):
                        if vid not in self._done:
                            owner_of.setdefault(vid, cid)
                except (aiohttp.ClientError, RuntimeError) as e:
                    log.info("YouTube search for %s's scheduled streams failed: %s", cid, e)
        for vid, cid in list(self._upcoming_ids.items()):
            if cid in followed:
                owner_of.setdefault(vid, cid)       # a waiting room found earlier, maybe gone from the feed
            else:
                del self._upcoming_ids[vid]         # nobody follows that channel any more
        out: Dict[str, Live] = {}
        upcoming: Dict[str, List[Dict[str, Any]]] = {}
        self.new_uploads = {}
        for part in chunks(list(owner_of), 50):
            # contentDetails (length) and player (its shape, with maxWidth) cost nothing extra: 1 unit per call
            data = await self._api("/videos", {"part": "snippet,liveStreamingDetails,contentDetails,player",
                                               "id": ",".join(part), "maxWidth": "640"})
            answered = {str(v.get("id") or "") for v in data.get("items") or []}
            for vid in part:
                if vid not in answered:
                    self._upcoming_ids.pop(vid, None)   # deleted or made private
            for v in data.get("items") or []:
                vid = str(v.get("id") or "")
                sn = v.get("snippet") or {}
                ld = v.get("liveStreamingDetails") or {}
                state = sn.get("liveBroadcastContent")
                cid = owner_of.get(vid, "")
                if state != "upcoming":
                    self._upcoming_ids.pop(vid, None)
                up = upload_info(v, now)
                if up:
                    self.new_uploads.setdefault(cid, []).append(up)
                if state == "live":
                    out[cid] = {"title": str(sn.get("title") or ""), "game": "",
                                "viewers": int(ld.get("concurrentViewers") or 0),
                                "started_at": iso_ts(str(ld.get("actualStartTime") or "")),
                                "url": f"https://www.youtube.com/watch?v={vid}",
                                "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault_live.jpg?t={int(time.time() // 300)}",
                                "video_id": vid}
                elif state == "upcoming":
                    self._upcoming_ids[vid] = cid
                    upcoming.setdefault(cid, []).append({
                        "title": str(sn.get("title") or ""), "at": iso_ts(str(ld.get("scheduledStartTime") or "")),
                        "url": f"https://www.youtube.com/watch?v={vid}", "platform": "youtube", "video_id": vid,
                        "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", "game": ""})
                else:
                    self._done.add(vid)       # an upload or a finished stream: never ask again
        self.upcoming = upcoming
        return out

    async def past_streams(self, channel_id: str, since: float, until: float) -> List[Dict[str, Any]]:
        """Finished livestreams that started in [since, until). A channel's uploads playlist is its id
        with UC → UU. About 2-4 quota units per channel. → [{started_at, ended_at, title, url, thumb}]"""
        if not self.api_key or not CHANNEL_ID.match(channel_id or ""):
            return []
        uploads = "UU" + channel_id[2:]
        ids: List[str] = []
        token = ""
        for _ in range(4):                    # at most 200 newest videos; plenty for a week or two
            params = {"part": "contentDetails", "playlistId": uploads, "maxResults": "50"}
            if token:
                params["pageToken"] = token
            data = await self._api("/playlistItems", params)
            oldest = None
            for it in data.get("items") or []:
                cd = it.get("contentDetails") or {}
                if cd.get("videoId"):
                    ids.append(str(cd["videoId"]))
                    t = iso_ts(str(cd.get("videoPublishedAt") or ""))
                    oldest = t if oldest is None or (t is not None and t < oldest) else oldest
            token = str(data.get("nextPageToken") or "")
            # a stream's video is published when it starts, so once the list is older than the week, stop
            if not token or (oldest is not None and oldest < since - 86400):
                break
        out = []
        for part in chunks(ids, 50):
            data = await self._api("/videos", {"part": "snippet,liveStreamingDetails", "id": ",".join(part)})
            for v in data.get("items") or []:
                ld = v.get("liveStreamingDetails") or {}
                start = iso_ts(str(ld.get("actualStartTime") or ""))
                end = iso_ts(str(ld.get("actualEndTime") or ""))
                if start is None or end is None or not (since <= start < until):
                    continue                  # an upload, a stream still live, or outside the week
                vid = str(v.get("id") or "")
                self._done.add(vid)
                out.append({"started_at": start, "ended_at": end, "title": str((v.get("snippet") or {}).get("title") or ""),
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"})
        return out

    async def videos(self, ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Community posts (flavrpromo/promo.py): what each video is now, 1 quota unit per 50 ids.
        → {video id: {state ("upcoming" / "live" / "past" / "upload"), at, end, title, channel_id,
        channel, thumb, url}}; a video YouTube doesn't return (deleted, private) is left out."""
        out: Dict[str, Dict[str, Any]] = {}
        if not self.api_key:
            return out
        for part in chunks(sorted(set(ids)), 50):
            data = await self._api("/videos", {"part": "snippet,liveStreamingDetails", "id": ",".join(part)})
            for v in data.get("items") or []:
                vid = str(v.get("id") or "")
                sn = v.get("snippet") or {}
                ld = v.get("liveStreamingDetails")
                state = sn.get("liveBroadcastContent")
                start = iso_ts(str((ld or {}).get("actualStartTime") or ""))
                end = iso_ts(str((ld or {}).get("actualEndTime") or ""))
                if not ld:
                    kind = "upload"            # a plain video, not a stream
                elif state == "live":
                    kind = "live"
                elif state == "upcoming":
                    kind = "upcoming"
                    start = iso_ts(str(ld.get("scheduledStartTime") or ""))
                else:
                    kind = "past" if start and end else "upload"
                out[vid] = {"state": kind, "at": start, "end": end, "title": str(sn.get("title") or ""),
                            "channel_id": str(sn.get("channelId") or ""), "channel": str(sn.get("channelTitle") or ""),
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}
        return out
