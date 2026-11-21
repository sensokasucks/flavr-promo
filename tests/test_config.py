from flavrpromo import config


def test_defaults_and_problems():
    s = config.load({})
    # its own port next to FlaVR Bot's 3870 (both stacks use host networking on the same PC)
    assert s.listen_port == 3871 and s.quiet_hours == (3, 11)
    assert len(config.problems(s)) == 2         # the Discord token and the owner; no Stream Core password
    assert s.import_dir == "/import"
    s = config.load({"DISCORD_TOKEN": "t", "OWNER_ID": "12", "QUIET_HOURS": "off",
                     "TWITCH_EVERY_SEC": "5"})
    assert config.problems(s) == []
    assert s.quiet_hours == (0, 0)
    assert s.twitch_every == 60                 # never faster than once a minute
    assert config.load({"QUIET_HOURS": "22-6"}).quiet_hours == (22, 6)
