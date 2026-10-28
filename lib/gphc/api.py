"""What a scenario sees: `run(t)` gets a Test; `t.player(name)` gives a Player on a real client.

A Player has low-level verbs (tp, hold, look_at, use, attack, say, block, entities) and a few composed actions
built from them (claim, break_block, place, attack_entity). Wrap any sequence in `with p.watch(observe) as r:`
to capture a before/after observation plus the chat lines the client received; `r.denied` matches GP's
"you can't do that here" messages. Scenarios record verdicts with `t.expect(name, condition, detail)`.
"""
import re
from contextlib import contextmanager
from dataclasses import dataclass, field

GROUND = -61          # top block of the default flat world; players stand at GROUND + 1
DENIAL = re.compile(r"permission to|claimed by|can't .* here|cannot .* here|not allowed|protected|belongs to", re.I)


@dataclass
class Result:
    before: object = None
    after: object = None
    chat: list = field(default_factory=list)
    targeted: str = None

    def said(self, pattern):
        return any(re.search(pattern, line) for line in self.chat)

    @property
    def denied(self): return self.said(DENIAL)
    @property
    def created(self): return self.said("Claim created")
    @property
    def changed(self): return self.before != self.after
    # for entity observations (lists); empty when nothing was observed
    @property
    def appeared(self): return [e for e in self.after or [] if e not in (self.before or [])]
    @property
    def gone(self): return [e for e in self.before or [] if e not in (self.after or [])]


class Player:
    def __init__(self, test, name):
        self.t, self.name = test, name
        self.bot = test.bots.launch(name)

    # server-side helpers
    def op(self): self.t.cmd(f"op {self.name}")
    def deop(self): self.t.cmd(f"deop {self.name}")
    def gamemode(self, mode): self.t.cmd(f"gamemode {mode} {self.name}")
    def give(self, item): self.t.cmd(f"give {self.name} {item}")

    def tp(self, x, y, z):
        """Teleport and wait until the client is there with chunks loaded."""
        self.t.cmd(f"tp {self.name} {x} {y} {z}")
        if not self.bot.call("wait_near", x=x, z=z):
            raise RuntimeError(f"{self.name} did not arrive at {x},{z}")
        self.bot.call("wait_loaded", x=x, y=y - 1, z=z)

    def riding(self):
        """Entity id the server says the player is mounted on, or None."""
        m = re.search(r'"([a-z_:]+)"', self.t.cmd(f"data get entity {self.name} RootVehicle.Entity.id"))
        return m.group(1) if m else None

    # client-side verbs
    def block(self, x, y, z): return self.bot.call("block", x=x, y=y, z=z)
    def entities(self, r=6): return self.bot.call("entities", r=r)
    def look_at(self, x, y, z): self.bot.call("look", x=x, y=y, z=z)
    def use(self): self.bot.call("use")
    def attack(self, secs=0.1): self.bot.call("attack", secs=secs)
    def say(self, text): self.bot.call("say", text=text)        # chat line, or /command, as the player

    def hold(self, item):
        """Give `item` and select it in the hotbar."""
        self.give(item)
        if self.bot.call("select_item", name=item.split(":")[-1]) is None:
            raise RuntimeError(f"{self.name} never received {item}")

    @contextmanager
    def watch(self, observe=None):
        """Snapshot `observe()` before and after the block, collect chat received meanwhile, log the Result."""
        r = Result(before=observe() if observe else None)
        self.bot.mark_chat()
        try:
            yield r
            r.after = observe() if observe else None
        finally:
            r.chat = self.bot.chat_since_mark()
            self.t.log(f"{self.name}: {r}")

    # composed actions
    def claim(self, corner1, corner2):
        """Right-click two ground corners with a golden shovel. corners are (x, z)."""
        self.hold("minecraft:golden_shovel")
        with self.watch() as r:
            for (x, z), dz in ((corner1, 1), (corner2, -1)):
                self.tp(x, GROUND + 1, z + dz)
                self.look_at(x + 0.5, GROUND + 0.5, z + 0.5)
                self.use()
        return r

    def break_block(self, x, y, z, secs=4.0):
        """Hold attack on a block; `changed` tells whether it broke."""
        self.tp(x, y + 1, z + 1)
        with self.watch(lambda: self.block(x, y, z)) as r:
            self.look_at(x + 0.5, y + 0.5, z + 0.5)
            self.attack(secs)
        return r

    def place(self, item, on):
        """Right-click the top face of block `on` holding `item`; `appeared` lists new entities nearby."""
        x, y, z = on
        self.hold(item)
        self.tp(x, y + 1, z + 2)
        with self.watch(self.entities) as r:
            self.look_at(x + 0.5, y + 1.0, z + 0.5)
            self.use()
        return r

    def sit(self, at):
        """Right-click the entity standing on block `at`; `after` is what the player then rides."""
        x, y, z = at
        self.tp(x, y + 1, z + 2)
        with self.watch(self.riding) as r:
            self.look_at(x + 0.5, y + 1.2, z + 0.5)
            self.use()
        return r

    def attack_entity(self, at, hits=6):
        """Punch whatever entity stands on block `at`; `gone` lists entities that disappeared."""
        x, y, z = at
        self.tp(x, y + 1, z + 2)
        with self.watch(self.entities) as r:
            self.look_at(x + 0.5, y + 1.3, z + 0.5)
            r.targeted = self.bot.call("targeted_entity")
            for _ in range(hits):
                self.attack()
            self.bot.call("sleep", secs=1)
        return r


class Test:
    def __init__(self, server, bots, out):
        self.server, self.bots, self.out = server, bots, out
        self.checks = []
        self.players = {}

    def player(self, name):
        """Launch a client for `name` (Offline1..Offline3) the first time; return the same Player afterwards."""
        if name not in self.players:
            self.players[name] = Player(self, name)
        return self.players[name]

    def cmd(self, line):
        """Run a console command on the server and return its output."""
        return self.server.cmd(line)

    def expect(self, name, ok, detail=""):
        self.checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})
        self.log(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else ""))
        return ok

    def log(self, msg):
        print(msg, file=self.out, flush=True)
