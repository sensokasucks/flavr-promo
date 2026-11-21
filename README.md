# FlaVR Promo

A Discord bot that promotes a group of streamers: it posts when someone goes live, keeps a weekly
stream calendar (a picture board per group), writes the Friday and Monday reviews, and gives you
copy-ready text for other Discords and X. It runs in Docker on any always-on computer at home
(a Linux box with Portainer is what it's made for).

It was split out of [FlaVR Bot](https://github.com/sensokasucks/flavr-bot) on 2026-11-20, so any
streamer group can run its own copy without the parts that only make sense for one streamer's setup.
FlaVR Bot keeps the [Stream Core](https://github.com/sensokasucks/flavr-leftovers) link (phone pings,
`/points`, `/queue`, `/said`, the after-stream recap), Wake-on-LAN and server care. The two run side
by side and don't need each other; with both, FlaVR Bot asks FlaVR Promo whether you're live
(`/live.json`) so its "Stream Core stopped answering" alarm stays quiet after a stream.

| Feature | What it does | Needs |
|---|---|---|
| **Go-live watcher** | Follows you, your group (FlaVR by default) and your other friends on YouTube, Twitch and Kick. Posts a card in each group's channel when someone goes live (one card even when they multistream; a quick restart edits the same card), and turns it into "was live for 2 h" with the Twitch VOD at the end, the **game** with a history tag (🆕 NEW GAME, 📖 PART 8, ⭐ STAPLE, 🔁 BACK AGAIN; from Twitch / Kick's category, or a known game named in a YouTube title, or `/friend game` by hand) and the games before it when they switch mid-stream ("Played: Valheim 1 h → Schedule I 2 h" at the end; `/friend games` lists someone's games), plus one of their **sign-off lines** ("🍗 otsu-nuggies"; several per person, picked at random, never the same twice in a row: `/friend signoff add`, or `/me signoff add` for their own). `/live` lists who's live. | Platform keys (each optional) |
| **/schedule** | Upcoming streams from Twitch schedules and YouTube scheduled streams | Twitch / YouTube keys |
| **Weekly calendar** | One picture board per group (FlaVR, Friends and any you add), Sunday to Saturday: past streams with their VOD picture and length, who's live now, and what's scheduled (Twitch schedules, YouTube waiting rooms, times set with `/friend schedule`). Posted Sunday 10 AM and edited all week; two **reviews** (owner 2026-11-20): the **week in review** Friday 10 AM (Monday to Thursday) and the **weekend in review** Monday 10 AM (Friday to Sunday), with real start and end times, a LATE NOTICE tag for streams scheduled under an hour ahead, and an **Also this week** list of videos, Shorts (vertical, 3 minutes or less), premieres and Twitch uploads / highlights; `/setup review-times` moves or switches them off, `/calendar view|post|share review:` makes one any time. A text list under the picture has every link. `/calendar view` shows any week (or, with `when`, just today / tomorrow / the weekend / a weekday, like `/calendar focus`; `/calendar post when:` posts that as an extra post); YouTube streams scheduled weeks ahead are found from each channel's 50 newest videos every 6 hours, with an optional deeper search (`/setup youtube-check`: off, daily, 48h or weekly; 100 quota units per channel a run); the owner gets a DM when a board changes (one per group, with that group's picture). Weeks the bot wasn't running for are filled in from the channels' past streams (Twitch past broadcasts, kept 7 days, 60 for partners; YouTube VODs; Kick has no such list), also by hand with `/calendar refresh`. To save YouTube quota, the free checks (live checks, each channel's RSS feed, Twitch) flag who streamed or posted a video, and before each review only those people get the one-time YouTube look-up (`/calendar refresh` asks about everyone). `/calendar share` (and automatically after the Sunday post and each review, `/pings` kind `share`) DMs you copy-ready text: a Discord version with time stamps for other servers, and an X version (schedule post + links reply, one long post, a 280-character thread, or an **X Article**: a page on the bot's web server, `/calendar/article`, with a Copy button that pastes headings, bold and links into X's Article editor: `/setup share-style`; X handles with `/friend x`, tagged only with `/setup share-style tag_people`; any @ in names and titles is defused so pasted text never tags or pings anyone). | `/setup calendar-channel`, platform keys |
| **Day focus posts** | The calendar for just **today**, **tomorrow**, **the weekend** (Friday to Sunday) or a weekday: big tiles for those days and the list with links under it. `/calendar focus` shows it to you (or posts it in the channel with `post`); in a talent channel it shows only that person. Optional automatic posts per group, each at a time you type ("10am", "8pm") or "off": a **Today** post (default 10 AM), an evening **Tomorrow** preview (default off) and a **This weekend** post on the day you pick (default Friday 10 AM); only when something's on, and edited through the day as people go live and end. `/calendar share when:` gives the copy-ready Discord and X text for just those days, and with `/pings` kind `share` on it follows each automatic post in your DMs. | `/setup day-posts` (off until a channel is picked) |
| **Community calendar** | For a self-promo channel: members with a role you pick add their own stream posts to a separate **Community** board (violet, its own Sunday post and Friday / Monday reviews, next to FlaVR and Friends). Long-press (phone) or right-click (PC) a post → **Apps → Add to community calendar** (a Twitch / Kick channel link asks "When?", e.g. "sat 8pm"; empty = live now), or `/community schedule link [when]`. Only YouTube stream, Twitch VOD and Twitch / Kick channel links count, each looked up through the official APIs (never opened); the bot then follows it from planned to live to finished (Twitch gets its VOD; Kick has no VOD API, so it links the channel's videos page). Opt-in per post: the bot never reads the channel by itself. Safety: your own posts only (moderators can add or remove anyone's), `PROMO_WEEKLY_LIMIT` posts a week each (7), duplicates merge, a deleted post drops off, **Remove from community calendar** or `/community remove`, and nothing pings anyone. `/community list` shows a week with numbers. | `/community roles add`, `/community report-channel` |
| **Talent channels** | One channel per person: `/talent channel Lulu #lulu-teala`. Their go-live card goes there AND in their group's channel (either can be switched off per person with `/talent options`), a pinned text card shows only their week (edited as it changes, a new one each Sunday 10 AM), and their own reviews post with the group's (Friday and Monday). `/live`, `/schedule`, `/calendar view` and `/calendar share` used in their channel show only them. `/talent link` connects their Discord account so they can manage their own entry with `/me` (weekly times, main platform, X handle, sign-off lines, hide for a vacation, where their cards go, their own share text); nobody else's. | Pin Messages (or Manage Messages) in their channel to pin the card |
| **Groups** | FlaVR, Friends and Community are built in; `/group add Art Pals #ff8800` makes your own, each with its own go-live channel, calendar board, reviews and share text. `/friend group` moves someone, `/group edit` renames or recolours (the built-in three too; FlaVR's board keeps the logo colours), `/group remove` deletes one and moves its people to Friends, `/group list` shows people and channels. | owner or Manage Server |
| **Calendar page + feed** | `http://<this PC>:3871/calendar` (live page, also an OBS Browser Source, `?group=friends` or a custom group's name, `?week=next`), `/calendar.png`, and `/calendar.ics` to add to Google / Apple Calendar on the home network | — |
| **Your DMs** | DMs you (so the Discord app on your phone buzzes): friends going live (one list every 10 minutes, off by default), calendar changes with the new picture, and the copy-ready share text after the Sunday post and each review. Quiet hours (`QUIET_HOURS`) hold them, except while you're live. `/pings` switches them. | — |
| **Hosts** | Two presenters, **Colette Cappuccino** (Marketing, loud and caffeinated, sticky notes) and **Clark** (Division Clerk, calm and dry, a filed report), take turns at random (never the same one three times in a row). Off until `/host setup on` (`only:` keeps one host). Go-live cards get the host's line above them ("☕ **Colette Cappuccino:** NEW GAME ALERT!! ..."), a new line when the game changes, and a closing line that reads out the sign-off line. Reviews **wait for your picks**: at review time the bot DMs you a link to `http://<this PC>:3871/hosts/pick` (one reminder after an hour), where you pick a line for each slot or type your own, can swap the host, preview the two cards and press **Post it**. Then the host's **opener card** (pose picture, their line, up to 3 highlights), the normal board and the host's **desk card** (highlight, a nudge for next time, sign-off) post in that order (1600 x 900, safe for X). A review you never pick never posts; `/calendar post review:` still posts the plain review at once. Both hosts' pictures are built in (`flavrpromo/host_art`, transparent WebP: poses happy / pointing / sleepy, desk, head, and chibi happy / pointing / sleepy / desk / head); `/host picture` replaces any one with your own upload (kept in `DATA_DIR/hosts`). Each review picks regular or chibi pictures at random for the opener and the desk card (the other style peeks on the opener); the picker page has a switch for each. The chibi peeks over the opener card, is the go-live face when there's no head picture, and presents the automatic **day posts** (a line on top of the post; in the picture a bubble and the chibi in a side column with up to 4 streams, a small badge in the header with more); `/host list` shows what's there, `/host preview` draws a card. | `/host setup on`, pictures optional |
| **/status** | The watcher (each platform's last check), who's live, and this PC's uptime, load and disk | — |

Only official, documented platform APIs are used, at a polite pace (Twitch every 2 minutes in one
call for up to 100 people, YouTube RSS + one API call every 10 minutes, Kick every 3 minutes).
The bot needs no privileged Discord intents.

**Settings page:** `http://<this PC>:3871/settings` (home network only, like the other pages): the
KoboldCpp address, password, creativity and lines per slot with a Test button (saved there, they win
over `KOBOLD_URL` / `KOBOLD_KEY`), hosts on / off, every host picture with upload and "back to
built-in", and every host line slot for both hosts as editable text. Linked at the top of it:

- `/settings/cards`: each host's character card (what KoboldCpp is sent) and what each slot asks
  for, with the whole prompt shown and a "try it" button; edits are kept apart from the built-in
  cards, "back to built-in" drops them.
- `/settings/article`: the article editor. Pick a group and a review or week; the X Article is cut
  into sections (host intro, summary, who streamed, each day, uploads, hashtags, host outro, your
  own text). Leave sections in or out, move them, regen one from the calendar, get new host lines
  (templates, or ✨ KoboldCpp), day pictures in the host's look (Colette's taped polaroids or
  Clark's filed photos, with their line about the day; layouts: pinned wall, timeline, spotlight, two columns, zigzag or cards,
  for the whole article or per day) or the board look, pick each host section's picture (opener card with chibi or regular
  big, desk card, one plain picture, or none), then open the finished article to copy.
- `/settings/commands`: a form for every slash command, run as the owner; the answer shows on the
  page (things a command posts in a channel still go there).

**AI lines (optional):** with `KOBOLD_URL` pointing at KoboldCpp (any PC at home, a model loaded;
`KOBOLD_KEY` if started with `--password`), the picker page also shows lines it writes in each host's
voice from their character cards (`flavrpromo/host_art/<host>/card.json`, the same cards work in
SillyTavern), marked ✨ and first in each slot, with a **Write more** button. Offline = template lines.

**Game details:** with the Twitch keys set, each game streamed is looked up once in IGDB (Twitch's
official game database): the go-live card links it (Steam page when it has one) and shows its genres,
a host's new-game line can name the genre, and KoboldCpp gets a short summary of new games.

## Set up

1. **Discord app** (its own, separate from FlaVR Bot's). [Discord developer
   portal](https://discord.com/developers/applications) → **New Application** (name it FlaVR Promo,
   add a picture) → **Bot** → **Reset Token**, copy it. No intents need switching on. Invite it:
   OAuth2 → URL Generator → scopes `bot` + `applications.commands`, permissions *Send Messages*,
   *Embed Links*, *Attach Files*, *Read Message History* (and *Pin Messages* or *Manage Messages* in
   talent channels, so their week card can be pinned) → open the link, pick your server.
2. **Run it** with Portainer: [docs/PORTAINER.md](docs/PORTAINER.md). The settings are environment
   variables, all listed in [.env.example](.env.example).
3. **In Discord:** `/setup live-channel` for each group, then `/friend add` (or `/friend import`) the
   people to follow. Add yourself with `owner: True` so `/schedule` knows who you are. For the
   weekly calendar, `/setup calendar-channel` for each group (the first post comes within a minute).
   Rename the built-in groups with `/group edit` if your group isn't called FlaVR.

Coming from FlaVR Bot? Step 2 copies everything over (people, channels, past streams, groups, the
channels picked in Discord), so step 3 is already done. See "Moving over from FlaVR Bot" in
[docs/PORTAINER.md](docs/PORTAINER.md).

Port 3871 is for the home network only. Never forward it on your router.

## Commands

See the top of [flavrpromo/bot.py](flavrpromo/bot.py). Owner-only answers are private ("only you can see this").

## Develop

```
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Code map: `flavrpromo/__main__.py` (start-up and wiring), `config.py` (environment), `store.py`
(SQLite in `/data`), `import_old.py` (the one-time copy from FlaVR Bot), `server.py` (the web
server, `/health`, `/live.json`), `pings.py` (your DMs), `watcher.py` + `platforms/` (go-live),
`bot.py` (Discord), `sysinfo.py`; the calendar is `calendar.py` (which streams go on which day),
`render.py` (the HTML board and its picture, Playwright Chromium), `calendar_post.py` (Discord posts,
reviews, pings), `focus.py` (day posts), `share.py` (Discord / X text), `signoff.py` (sign-off lines), `games.py` (game history and tags), `gameinfo.py` (IGDB game details), `kobold.py` (KoboldCpp lines), `settings_page.py` (/settings), `card_page.py` (/settings/cards), `article_editor.py` (/settings/article), `command_forms.py` (/settings/commands), `hosts.py` +
`host_cards.py` + `host_picker.py` (Colette and Clark, their cards, the review line picker), `talent.py`, `promo.py`
(community calendar), `groups.py` and `web.py` (page, picture, .ics, X Article). The calendar
picture needs `playwright install chromium` outside Docker (or `CHROMIUM_PATH`); without it posts
go out as text only.

## License

GPL-3.0 (see [LICENSE](LICENSE)). discord.py is MIT, tzdata is Apache-2.0.
