"""Headless Minecraft clients launched through HeadlessMc, driven over a localhost socket by client/gpbot.py."""
import json, re, shutil, socket, sys, time
from . import env

BOT_SCRIPT = env.REPO / "client" / "gpbot.py"
CHAT = re.compile(r"\[CHAT\] (.*)")


class Bots:
    """Accepts bot connections on the fixed bot port; one Bot per launched client."""

    def __init__(self, mc, server, run_dir):
        self.mc, self.server, self.run_dir = mc, server, run_dir
        ms = env.game_dir(mc) / "minescript"
        if f"gpbot {server.bot_port}" not in env.read_from(ms / "config.txt"):
            sys.exit(f"Minescript autorun not configured for MC {mc}; run `gphc setup --mc {mc}`")
        shutil.copy(BOT_SCRIPT, ms / "gpbot.py")
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", server.bot_port))
        self.listener.listen()
        self.listener.settimeout(5)
        self.bots = []

    def launch(self, name, timeout=180):
        env.hmc(self.mc, "account", "select", name, capture_output=True)
        log = self.run_dir / f"client-{name}.log"
        proc = env.launch_client(self.mc, log, "--jvm", "-Xmx2G", "--server", f"127.0.0.1:{self.server.port}")
        deadline, server_log_start = time.time() + timeout, self.server.log.stat().st_size
        while time.time() < deadline:
            try:
                conn, _ = self.listener.accept()
            except socket.timeout:
                if proc.poll() is not None:
                    raise RuntimeError(f"client {name} exited before joining; see {log}")
                kicked = re.search(rf"Disconnecting {name} .*?: (.*)", env.read_from(self.server.log, server_log_start))
                if kicked:
                    env.terminate(proc)
                    raise RuntimeError(f"server rejected {name}: {kicked.group(1)}")
                continue
            bot = Bot(name, conn, proc, log)
            hello = bot.recv()
            if hello.get("hello") != name:
                env.terminate(proc)
                raise RuntimeError(f"expected {name}, bot said {hello}")
            self.bots.append(bot)
            return bot
        env.terminate(proc)
        raise TimeoutError(f"client {name} did not join within {timeout}s; see {log}")

    def kill_all(self):
        for bot in self.bots:
            env.terminate(bot.proc)
        self.bots.clear()
        self.listener.close()


class Bot:
    def __init__(self, name, conn, proc, log):
        self.name, self.conn, self.proc, self.log = name, conn, proc, log
        conn.settimeout(120)
        self.rfile = conn.makefile("r")
        self.chat_offset = 0

    def recv(self):
        line = self.rfile.readline()
        if not line:
            raise ConnectionError(f"bot {self.name} disconnected; see {self.log}")
        return json.loads(line)

    def call(self, op, **args):
        self.conn.sendall((json.dumps({"op": op, **args}) + "\n").encode())
        reply = self.recv()
        if "error" in reply:
            raise RuntimeError(f"bot {self.name} {op}: {reply['error']}")
        return reply.get("result")

    def mark_chat(self):
        self.chat_offset = self.log.stat().st_size

    def chat_since_mark(self):
        return CHAT.findall(env.read_from(self.log, self.chat_offset))
