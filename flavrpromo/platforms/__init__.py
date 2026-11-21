"""
Platform look-ups for the go-live watcher (flavrpromo/watcher.py). Official, documented APIs only,
asked politely (batched, a few minutes apart), so no platform sees this as a scraper:

  twitch.py   Helix: app sign-in (client credentials), users, streams (100 per call), schedule, videos
  youtube.py  each channel's public RSS feed + one Data API videos.list call (free key, 1 unit per 50 videos)
  kick.py     Kick's public API: app sign-in, channels (up to 50 slugs per call)

Every checker has the same shape:
  await checker.resolve(handles) -> {handle: {"platform_id", "display", "avatar"} or None}
  await checker.live(accounts)   -> {platform_id: Live}   (only the ones live right now)

``Live`` is a plain dict: title, url, thumb, game, viewers, started_at (unix s).
"""

from typing import Any, Dict

Live = Dict[str, Any]
UA = "FlaVR-Promo/1.0 (+https://github.com/sensokasucks/flavr-promo)"
