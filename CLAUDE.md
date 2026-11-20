# FlaVR Promo — notes for Claude

Discord bot that promotes a group of streamers: go-live cards, the weekly calendar boards, the
Friday / Monday reviews, day focus posts, talent channels, the community calendar and copy-ready
share text. Python 3.12, discord.py, aiohttp, SQLite, Playwright Chromium for the pictures. Runs in
Docker on the owner's Linux box via Portainer. Split from FlaVR Bot (sensokasucks/flavr-bot) on
2026-11-20; Stream Core, Wake-on-LAN, server care and the after-stream recap stay there. Other
streamer groups should be able to run their own copy, so keep owner-specific names in settings.

Rules

- Every code change carries human-readable comments: what a file is for, who calls a function,
  which setting drives it, units, and what must stay in sync. Fix comments a change makes wrong.
- Settings are environment variables: `flavrpromo/config.py` and `.env.example` stay in step.
- `/live.json` (flavrpromo/server.py) is read by FlaVR Bot (its `PROMO_URL`); keep its shape or
  change both repos together.
- Platforms: official, documented APIs only, batched and slow (no page scraping). The owner
  doesn't want to risk a ban.
- Every Discord message uses `allowed_mentions` none.
- Weekly calendar decisions (owner): week runs Sunday to Saturday; preview Sunday 10 AM; reviews
  Friday 10 AM (Mon-Thu) and Monday 10 AM (Fri-Sun), no Saturday recap (2026-11-20); YouTube's costly
  past-stream look-ups only for people the free checks saw active; FlaVR board uses the logo and
  its colours, Friends board plain teal; main platform default YouTube. Plan docs (Claude Docs):
  "Weekly FlaVR calendar plan", "FlaVR Bot presenter plan" (sign-off lines, game history, hosts).
- Tests: `python -m pytest` (no network). CI runs them on every push.
- `.bat` files (if any) stay ASCII + CRLF (`.gitattributes`).
