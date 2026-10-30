# gp-headless-client

Tests GriefPrevention with real Minecraft clients. `gphc run` boots a local Paper server with the
plugin, launches headless clients (HeadlessMc + Fabric + Minescript), plays a short Python scenario
and prints a JSON verdict.

## Quickstart

Needs Python 3.11.4+, macOS or Linux, ~6 GB RAM for two bots. Setup downloads ~550 MB and takes ~750
MB disk. Java comes with setup: each MC version pins the exact major its client needs (25 for 26.x);
set `GPHC_JAVA_25=<java home>` to use your own. State lives in `GPHC_HOME` (default `~/.gphc`).

```bash
./gphc setup                                   # once: pinned jars, Fabric, offline accounts, warm-up
./gphc run examples/claim_protects_blocks.py --gp-jar path/to/GriefPrevention.jar   # smoke test
./gphc run my_repro.py --gp-jar …              # --mc 26.2 selects another pinned version
./gphc run my_repro.py --gp-jar … --server-jar path/to/spigot-26.3.jar   # another server jar (e.g. BuildTools Spigot)
```

```json
{"scenario": "issue_2644_cushions", "mc": "26.3", "gp_version": "16.18.7", "gp_jar": "/path/GriefPrevention.jar", "ok": false,
 "checks": [{"name": "cushion placement denied", "ok": false, "detail": "['entity.minecraft.cushion@[-4, -60, -2]']"}],
 "error": null, "run_dir": "/Users/me/.gphc/runs/20261022-004216-issue_2644_cushions"}
```

Exit code is non-zero when a check fails or the scenario errors. `run_dir` holds `report.json`,
`trace.log` (every action and its observations), `server.log` and one `client-<name>.log` per bot.
A run takes about a minute: ~15 s server boot, ~20 s per client boot, a few seconds per action.
`--keep` leaves the server up for `./gphc rcon <command>` and `./gphc stop`.

## Scenarios

A scenario is a Python file with `run(t)`. `examples/` holds a smoke test and a template for a real
issue repro; write new ones wherever the work happens.

```python
"""One line: what this proves or reproduces."""
from gphc.api import GROUND           # top block of the flat world (-61); players stand at GROUND + 1

MC = ["26.3"]                          # optional: versions the scenario applies to
GP_CONFIG = {"GriefPrevention.Spam.LoginCooldownSeconds": 60}   # optional: GP config.yml overrides, dotted keys

def run(t):
    owner = t.player("Offline1")                       # launches a client; Offline1..Offline3 exist
    t.expect("claim created", owner.claim((-12, -8), (-3, 1)).created)
    r = t.player("Offline2").break_block(-5, GROUND, -3)   # never trusted, never op'd
    t.expect("inside claim survives", not r.changed, f"{r.before} -> {r.after}")
    t.expect("GP denied it", r.denied, r.chat)
```

| Call | Does | Result |
|---|---|---|
| `t.player(name)` | launch a client (once per name) | `Player` |
| `t.login(name)` | launch a client the server may reject (ban, cooldown, whitelist) | `.player` or `.rejected` reason |
| `p.quit()` | disconnect; `t.player(name)` launches a fresh client afterwards | |
| `t.expect(name, ok, detail="")` | record a check | `ok` |
| `t.cmd("...")` | console command over RCON | output text |
| `p.claim((x1, z1), (x2, z2))` | golden shovel on two ground corners | `.created`, `.chat` |
| `p.break_block(x, y, z, secs=4)` | hold attack on a block | `.before`, `.after`, `.changed`, `.denied`, `.chat` |
| `p.place(item, on=(x, y, z))` | right-click the top face holding `item` | `.appeared`, `.denied`, `.chat` |
| `p.attack_entity(at=(x, y, z))` | punch the entity standing on a block | `.targeted`, `.gone`, `.denied`, `.chat` |
| `p.sit(at=(x, y, z))` | right-click the entity standing on a block | `.after` is what the player now rides (`p.riding()`), `.denied`, `.chat` |
| `p.op() / p.deop() / p.give(item) / p.gamemode(m) / p.tp(x, y, z)` | server-side helpers (`tp` waits for chunks) | |
| `p.hold(item) / p.look_at(x, y, z) / p.use() / p.attack(secs) / p.say(text)` | client-side verbs | |
| `p.block(x, y, z)` / `p.entities(r=6)` | block id / nearby entities as the client sees them | string / list |
| `with p.watch(observe) as r:` | capture chat and `observe()` before/after any verbs | `.before`, `.after`, `.changed`, `.appeared`, `.gone`, `.denied`, `.said(rx)`, `.chat` |

`chat` is what the client received since the action started; `denied` matches GP's refusal messages
(`api.DENIAL`). The composed actions are a few verbs inside `watch`; copy one to test a chest, door,
sheep or `/trust` flow:

```python
p.tp(x, y + 1, z + 2)
with p.watch(lambda: p.block(x, y, z)) as r:      # or p.entities, or nothing
    p.look_at(x + 0.5, y + 0.5, z + 0.5); p.use()
```
Every run starts from a fresh flat world (peaceful, spawn protection off), empty GP claim data and a fresh
GP `config.yml` holding `GriefPrevention.Spam.LoginCooldownSeconds: 0` (so bots can reconnect) plus the
scenario's `GP_CONFIG`; GP fills in the rest with defaults.

Worth it when the question is what Paper actually fires when a real player does X (new blocks,
entities, interactions). Plain claim-logic questions are cheaper as unit tests in the GP repo.

## How it works

- `setup` downloads the jars and the Temurin JRE pinned in `pins.json` (sha256-checked),
  lets HeadlessMc install Fabric and fetch Mojang's assets (sounds and textures as stubs:
  `hmc.assets.dummy`), writes offline accounts into HeadlessMc's account file, drops Fabric API and
  Minescript into the client's `mods/`, points Minescript's autorun at the bot port, and boots Paper
  once so it patches its vanilla jar. Re-run it after changing `pins.json`. HeadlessMc, the client and
  Paper all run on the MC version's pinned Java (`-Dhmc.java.versions`).
- `run` starts Paper with RCON (`lib/gphc/server.py`); each `t.player` launches `headlessmc launch
  --offline --headless --server …` (`lib/gphc/client.py`). Minescript autoruns `client/gpbot.py`
  on world join, which connects back to game port + 2000 and executes low-level actions (look, use,
  attack, select item, read blocks and entities). `lib/gphc/api.py` composes those into the calls
  above: teleport via RCON, wait for chunks, act, read `[CHAT]` lines from the client log.

## Gotchas

- One run at a time per MC version: ports (game, +1000 RCON, +2000 bot socket) and the client game
  dir are shared.
- `--server-jar` boots that jar in its own server dir (`servers/<mc>-<jar stem>`) on the same ports; the
  first Spigot boot extracts its bundle and takes longer.
- A denied *break* produces a GP chat message; a denied *left-click* alone is silent.
- Right-clicks hit the nearest block along the view ray, so actions teleport the bot next to the
  target.
- Expected client log noise: `OpenAL 1.1 not supported`, Realms and profile-key 401s.
- Minescript chat listeners do not see plugin messages; the client log does.

## Bumping versions

`pins.json` holds URL + sha256 per piece.
- Paper: `https://fill.papermc.io/v3/projects/paper/versions/<mc>/builds`. 
- Fabric API and Minescript: Modrinth (`https://api.modrinth.com/v2/version_file/<sha1>` resolves a known jar). 
- HeadlessMc: GitHub releases.
- Fabric Loader is whatever HeadlessMc's installer picks.
- Java: an MC version's `java` is `javaVersion.majorVersion` from its Mojang version manifest; JRE pins come from
`https://api.adoptium.net/v3/assets/latest/<major>/hotspot?image_type=jre&os=<mac|linux>&architecture=<aarch64|x64>`.
