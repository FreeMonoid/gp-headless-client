# Runs inside the Minecraft client via Minescript (autorun). Connects to the gphc driver and executes
# low-level player actions on request. No GriefPrevention knowledge here; scenarios compose these.
import json, socket, sys, time
from minescript import *

PORT = int(sys.argv[1])


def poll(cond, secs):
    """Call `cond` every 0.2 s until it returns something other than None/False, or `secs` pass."""
    for _ in range(int(secs * 5)):
        r = cond()
        if r is not None and r is not False:
            return r
        time.sleep(0.2)
    return None


def wait_loaded(x, y, z):
    return poll(lambda: "void_air" not in getblock(x, y, z), 30) or False


def wait_near(x, z):
    def near():
        px, _, pz = player_position()
        return abs(px - x) + abs(pz - z) < 4
    return poll(near, 30) or False


def look(x, y, z):
    player_look_at(x, y, z)
    time.sleep(0.3)


def press(fn, secs):
    # Input is silently ignored under any screen ("Loading terrain" right after join, chat, death, containers)
    if not poll(lambda: screen_name() is None, 30):
        raise RuntimeError(f"screen {screen_name()} still open")
    fn(True); time.sleep(secs); fn(False); time.sleep(1.0)


def select_item(name):
    slot = poll(lambda: next((it.slot for it in player_inventory() if name in it.item), None), 10)
    if slot is None:
        return None
    if slot > 8:
        slot = player_inventory_slot_to_hotbar(slot)
    player_inventory_select_slot(slot)
    return slot


def nearby(r):
    return sorted(f"{e.type}@{[round(v) for v in e.position]}" for e in entities(max_distance=r) if not e.local)


OPS = {
    "block": getblock,
    "wait_loaded": wait_loaded,
    "wait_near": wait_near,
    "look": look,
    "attack": lambda secs: press(player_press_attack, secs),
    "use": lambda: press(player_press_use, 0.15),
    "select_item": select_item,
    "entities": nearby,
    "targeted_entity": lambda: getattr(player_get_targeted_entity(6), "type", None),
    "say": lambda text: execute(text) if text.startswith("/") else chat(text),
    "sleep": lambda secs: time.sleep(secs),
}

# Autorun fires while "Loading terrain" is still up; a teleport and break sent then never reach GP. Say hello once
# in the world, or not at all so the driver times out loudly.
if not poll(lambda: screen_name() is None, 60):
    sys.exit(f"screen {screen_name()} never closed")
sock = socket.create_connection(("127.0.0.1", PORT))
f = sock.makefile("rw")
f.write(json.dumps({"hello": player_name()}) + "\n"); f.flush()
for line in f:
    req = json.loads(line)
    op = req.pop("op")
    try:
        reply = {"result": OPS[op](**req)}
    except Exception as e:
        reply = {"error": f"{type(e).__name__}: {e}"}
    f.write(json.dumps(reply) + "\n"); f.flush()
