"""GriefPrevention#2644: untrusted player can place and break cushions inside a claim (MC 26.3+)."""
from gphc.api import GROUND

MC = ["26.3"]


def run(t):
    owner = t.player("Offline1")
    t.expect("claim created", owner.claim((-12, -8), (-3, 1)).created)
    mine = owner.place("minecraft:blue_cushion", on=(-6, GROUND, -5))
    t.expect("owner placement inside allowed", mine.appeared, mine.chat)
    seat = owner.place("minecraft:blue_cushion", on=(-9, GROUND, -2))
    t.expect("owner placement of a seat allowed", seat.appeared, seat.chat)
    owner.tp(-11, GROUND + 1, 1)      # out of the way of Offline2's punches

    other = t.player("Offline2")
    placed = other.place("minecraft:red_cushion", on=(-5, GROUND, -3))
    t.expect("untrusted placement inside denied", not placed.appeared, placed.appeared or placed.chat)

    broken = other.attack_entity(at=(-6, GROUND, -5))
    t.expect("untrusted break inside denied", not broken.gone, broken.gone or broken.chat)

    sat = other.sit(at=(-9, GROUND, -2))
    t.expect("untrusted sitting allowed", sat.after == "minecraft:cushion", sat.after or sat.chat)

    outside = other.place("minecraft:red_cushion", on=(3, GROUND, -6))
    t.expect("placement outside allowed", outside.appeared, outside.chat)
