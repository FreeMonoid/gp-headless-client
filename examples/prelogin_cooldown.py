"""GP's login cooldown and smart-ban hook no longer listen to PlayerLoginEvent (#2489): Paper stops warning,
and the cooldown still rejects a quick reconnect on Paper and Spigot alike."""
import re, time
from gphc import env

COOLDOWN = 60
GP_CONFIG = {"GriefPrevention.Spam.LoginCooldownSeconds": COOLDOWN}


def run(t):
    t.expect("no PlayerLoginEvent warning", "HorriblePlayerLoginEventHack" not in env.read_from(t.server.log))

    t.cmd("deop Offline1")                             # a leftover op would be exempt from the cooldown
    t.player("Offline1").quit()
    second = t.login("Offline1")
    t.expect("quick reconnect rejected", second.rejected is not None, second.rejected)
    wait = re.fullmatch(r"You must wait (\d+) seconds before logging-in again\.", second.rejected or "")
    t.expect("cooldown message with remaining seconds", wait and 0 < int(wait.group(1)) <= COOLDOWN, second.rejected)

    t.cmd("op Offline2")                               # griefprevention.spam defaults to op: exempt
    t.player("Offline2").quit()
    exempt = t.login("Offline2")
    t.expect("griefprevention.spam holder reconnects", exempt.player is not None, exempt.rejected)
    t.cmd("deop Offline2")

    if wait:
        time.sleep(int(wait.group(1)) + 2)
        third = t.login("Offline1")
        t.expect("reconnect after cooldown allowed", third.player is not None, third.rejected)
