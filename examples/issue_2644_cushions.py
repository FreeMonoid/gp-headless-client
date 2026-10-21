"""GriefPrevention#2644: untrusted player can place and break cushions inside a claim (MC 26.3+)."""
from gphc.api import GROUND

MC = ["26.3"]


def run(t):
    owner = t.player("Offline1")
    t.expect("claim created", owner.claim((-12, -8), (-3, 1)).created)

    other = t.player("Offline2")
    placed = other.place("minecraft:red_cushion", on=(-5, GROUND, -3))
    t.expect("cushion placement denied", not placed.appeared, placed.appeared or placed.chat)

    if placed.appeared:
        broken = other.attack_entity(at=(-5, GROUND, -3))
        t.expect("cushion break denied", not broken.gone, broken.gone or broken.chat)
