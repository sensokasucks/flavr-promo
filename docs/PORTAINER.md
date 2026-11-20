# Running FlaVR Promo with Portainer

The stack builds the image from this GitHub repo, so updates are a "Pull and redeploy" (or automatic).
FlaVR Promo is its own stack, next to FlaVR Bot's if you run both (split 2026-11-20).

1. Portainer → your environment → **Stacks** → **Add stack**.
2. Name: `flavr-promo`. Build method: **Repository**.
3. Repository URL: `https://github.com/sensokasucks/flavr-promo`, reference `refs/heads/main`,
   compose path `docker-compose.yml`. (A private repo needs **Authentication** with a GitHub
   personal access token that can read it.)
4. **Environment variables** → *Advanced mode* → paste [.env.example](../.env.example) and fill it in.
   At least `DISCORD_TOKEN` (FlaVR Promo's own Discord app, not FlaVR Bot's) and `OWNER_ID`, plus the
   platform keys you have.
5. Optional: **GitOps updates** on (polling, e.g. every 5 minutes) so a merge into `main` redeploys by itself.
6. **Deploy the stack.** Logs: Containers → flavr-promo → Logs. A healthy start ends with
   `Calendar pages on 0.0.0.0:3871` and `Discord: logged in as FlaVR Promo#…`.

## Moving over from FlaVR Bot

Before the split, FlaVR Bot did all of this. FlaVR Promo copies its data once, on its first start:

1. Find FlaVR Bot's data folder on the PC. With the usual stack name it is
   `/var/lib/docker/volumes/flavr-bot_flavr-bot-data/_data` (Portainer → Volumes →
   `flavr-bot_flavr-bot-data` shows the mount point).
2. In step 4 above, set `IMPORT_DIR` to that folder. The stack mounts it read-only, so FlaVR Bot can
   keep running while the copy is made.
3. Deploy. The log says `Copied FlaVR Bot's calendar data: N people, N streams`. People, channels,
   past streams, schedules, groups, talent channels, community posts and the settings picked in
   Discord all come over; Stream Core's chat copy and alerts stay with FlaVR Bot.
4. Then update FlaVR Bot to the version without the calendar and go-live posts (its own pull request),
   so the two don't both post. Until then each go-live would be posted twice.
5. Old calendar and go-live posts were made by FlaVR Bot and can't be edited by FlaVR Promo (Discord
   only lets a bot edit its own messages). This week's calendar board is posted fresh; delete FlaVR
   Bot's old one if you like.

The copy only happens while FlaVR Promo has no database yet. To run it again, stop the stack and
delete `flavr_promo.db` from the `flavr-promo_flavr-promo-data` volume. `IMPORT_DIR` can stay set or be
cleared afterwards; it is never written to.

## Notes

* The container uses the host's network (`network_mode: host`), so the calendar page is at this PC's
  own address, port 3871 (`LISTEN_PORT`). FlaVR Bot can ask `http://<this PC>:3871/live.json` whether
  you're live (its `PROMO_URL` setting).
* The database is in the named volume `flavr-promo_flavr-promo-data` (`/data` inside). Redeploys keep it.
* If this PC runs a firewall (ufw), allow the port from the home network only:
  `sudo ufw allow from 192.168.1.0/24 to any port 3871 proto tcp` (use your own network). Never forward
  it on the router.
* Changing a setting: Stacks → flavr-promo → Environment variables → edit → **Update the stack**.
