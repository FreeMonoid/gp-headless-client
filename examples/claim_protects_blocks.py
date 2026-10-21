"""Baseline: a claim stops an untrusted player breaking blocks inside it but not outside."""
from gphc.api import GROUND


def run(t):
    owner = t.player("Offline1")
    r = owner.claim((-12, -8), (-3, 1))
    t.expect("claim created", r.created, r.chat)

    other = t.player("Offline2")
    inside = other.break_block(-5, GROUND, -3)
    t.expect("block inside claim survives", not inside.changed, f"{inside.before} -> {inside.after}")
    t.expect("GP denies the break", inside.denied, inside.chat)

    outside = other.break_block(3, GROUND, -6)
    t.expect("block outside claim breaks", outside.changed, f"{outside.before} -> {outside.after}")
