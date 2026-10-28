"""Paper server under GPHC_HOME/servers/<mc>, driven over RCON. `jar` swaps in another server jar (Spigot) in its own dir."""
import re, shutil, socket, struct, subprocess, zipfile
from pathlib import Path
from . import env

RCON_PASSWORD = "gphc"
GP_CONFIG = """\
GriefPrevention:
  Spam:
    LoginCooldownSeconds: 0
"""


class Server:
    def __init__(self, mc, jar=None):
        pins = env.mc_pins(mc)
        self.mc, self.port = mc, pins["port"]
        self.rcon_port = self.port + 1000
        self.bot_port = self.port + 2000      # where clients call the driver back (client/gpbot.py)
        self.jar = Path(jar) if jar else env.DL / f"paper-{mc}-{pins['paper']['build']}.jar"
        self.dir = env.server_dir(mc) if jar is None else env.server_dir(f"{mc}-{self.jar.stem}")
        self.log = self.dir / "server.log"
        self.proc = self.rcon = self.gp_version = None

    def prepare(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "eula.txt").write_text("eula=true\n")
        props = {
            "online-mode": "false", "server-ip": "127.0.0.1", "server-port": self.port,
            "enable-rcon": "true", "rcon.port": self.rcon_port, "rcon.password": RCON_PASSWORD,
            "level-type": "minecraft\\:flat", "level-name": "world", "generate-structures": "false",
            "allow-nether": "false", "difficulty": "peaceful", "spawn-monsters": "false", "spawn-animals": "false",
            "spawn-protection": "0", "view-distance": "6", "simulation-distance": "4", "max-players": "10",
            "enforce-secure-profile": "false", "sync-chunk-writes": "false", "white-list": "false", "motd": "gphc",
        }
        (self.dir / "server.properties").write_text("".join(f"{k}={v}\n" for k, v in props.items()))
        (self.dir / "plugins").mkdir(exist_ok=True)

    def reset(self):
        """Fresh world and fresh GP claim/player data; GP config.yml survives."""
        for p in self.dir.glob("world*"):
            shutil.rmtree(p)
        gpdata = self.dir / "plugins" / "GriefPreventionData"
        for sub in ("ClaimData", "PlayerData"):
            shutil.rmtree(gpdata / sub, ignore_errors=True)
        gpdata.mkdir(parents=True, exist_ok=True)
        cfg = gpdata / "config.yml"
        if not cfg.exists():
            cfg.write_text(GP_CONFIG)

    def start(self, gp_jar):
        self.prepare()
        self.reset()
        plugin = self.dir / "plugins" / "GriefPrevention.jar"
        plugin.unlink(missing_ok=True)
        if gp_jar:
            shutil.copy(gp_jar, plugin)
            self.gp_version = plugin_version(plugin)
        self.proc = subprocess.Popen(
            [env.java(self.mc), "-Xmx2G", "-jar", str(self.jar), "nogui"], cwd=self.dir, stdin=subprocess.PIPE,
            stdout=open(self.log, "w"), stderr=subprocess.STDOUT, start_new_session=True)
        env.wait_for(self.log, r"\]: Done \(", self.proc, 180, "server boot")
        self.connect()

    def connect(self):
        """Attach to the RCON port of a running server (ours, or one left up with --keep)."""
        self.rcon = Rcon("127.0.0.1", self.rcon_port, RCON_PASSWORD)
        return self

    def cmd(self, line):
        return strip_colors(self.rcon.cmd(line))

    def stop(self):
        if not self.proc:
            return
        try:
            if self.rcon:
                self.rcon.cmd("stop")
                self.rcon.close()
            self.proc.wait(60)
        except Exception:
            env.terminate(self.proc)
        self.proc = self.rcon = None


def strip_colors(s):
    return re.sub(r"\x1b\[[0-9;]*m|§.", "", s)


def plugin_version(jar):
    with zipfile.ZipFile(jar) as z:
        for line in z.read("plugin.yml").decode().splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip().strip("'\"")


class Rcon:
    """Minimal Source RCON client (what Paper speaks)."""
    AUTH, CMD = 3, 2

    def __init__(self, host, port, password):
        self.sock = socket.create_connection((host, port), timeout=10)
        self._id = 0
        if self._send(self.AUTH, password)[0] == -1:
            raise RuntimeError("rcon auth failed")

    def _send(self, kind, payload):
        self._id += 1
        body = struct.pack("<ii", self._id, kind) + payload.encode() + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(body)) + body)
        (length,) = struct.unpack("<i", self._read(4))
        data = self._read(length)
        return struct.unpack("<i", data[:4])[0], data[8:-2].decode(errors="replace")

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("rcon closed")
            buf += chunk
        return buf

    def cmd(self, line):
        return self._send(self.CMD, line)[1]

    def close(self):
        self.sock.close()
