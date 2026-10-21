"""`gphc setup`: download pinned pieces, install Fabric via HeadlessMc, create offline accounts, warm up."""
import hashlib, json, shutil, sys, tarfile, urllib.request, uuid
from . import env
from .server import Server

ACCOUNTS = ["Offline1", "Offline2", "Offline3"]


def download(name, pin):
    dest = env.DL / name
    if dest.exists() and sha256(dest) == pin["sha256"]:
        return dest
    print(f"downloading {name}", flush=True)
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(pin["url"], headers={"User-Agent": "gphc (github.com/FreeMonoid/gp-headless-client)"})
    with urllib.request.urlopen(req) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    if sha256(tmp) != pin["sha256"]:
        tmp.unlink()
        sys.exit(f"{name}: sha256 mismatch")
    tmp.rename(dest)
    return dest


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def offline_uuid(name):
    """Same derivation Bukkit uses for offline-mode players (name-based UUID v3, no namespace)."""
    return str(uuid.UUID(bytes=hashlib.md5(f"OfflinePlayer:{name}".encode()).digest(), version=3))


def write_accounts():
    path = env.CLIENT / "data" / "headlessmc" / ".auth" / "offline" / ".accounts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    accounts = {n: {"provider": "offline", "name": n, "uuid": offline_uuid(n), "token": "", "type": "msa", "xuid": ""}
                for n in ACCOUNTS}
    path.write_text(json.dumps({"accounts": accounts, "version": 0}, indent=2))


def install_java(mc):
    """Unpack the pinned JRE for `mc` so its Java home is env.jre_dir, unless GPHC_JAVA_<major> is set."""
    major = env.mc_pins(mc)["java"]
    if env.java_override(major) or (dest := env.jre_dir(major)).exists():
        return
    archive = download(dest.name + ".tar.gz", env.jre_pin(major))
    tmp = dest.with_name(dest.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    with tarfile.open(archive) as tar:
        tar.extractall(tmp, filter="data")
    java = next(tmp.glob("*/bin/java"), None) or next(tmp.glob("*/Contents/Home/bin/java"))  # macOS: inside a bundle
    java.parents[1].rename(dest)
    shutil.rmtree(tmp)
    archive.unlink()


def setup(mc):
    pins = env.mc_pins(mc)
    server = Server(mc)
    env.DL.mkdir(parents=True, exist_ok=True)
    install_java(mc)
    download("headlessmc.jar", env.PINS["headlessmc"])
    download(server.jar.name, pins["paper"])
    mods = [download(f"fabric-api-{pins['fabric_api']['version']}.jar", pins["fabric_api"]),
            download(f"minescript-fabric-{mc}-{pins['minescript']['version']}.jar", pins["minescript"])]

    if not list(env.minecraft_dir().glob(f"versions/fabric-loader-*-{mc}")):
        print(f"installing fabric {mc} via HeadlessMc", flush=True)
        env.hmc(mc, "version", "install", "fabric", mc, check=True)
    write_accounts()
    env.hmc(mc, "account", "select", ACCOUNTS[0], capture_output=True)

    game = env.game_dir(mc)
    (game / "mods").mkdir(parents=True, exist_ok=True)
    (game / "minescript").mkdir(exist_ok=True)
    for jar in mods:
        shutil.copy(jar, game / "mods" / jar.name)
    (game / "options.txt").write_text("pauseOnLostFocus:false\nonboardAccessibility:false\nnarrator:0\n")
    (game / "minescript" / "config.txt").write_text(f'python="{sys.executable}"\nautorun[*]=gpbot {server.bot_port}\n')

    if not (env.minecraft_dir() / "assets" / "indexes").exists():
        print("first client launch to fetch assets", flush=True)
        log = env.CLIENT / f"warm-{mc}.log"
        proc = env.launch_client(mc, log)
        env.wait_for(log, "Minescript mod starting", proc, 600, "client warm-up")
        env.terminate(proc)

    if not (server.dir / "cache").exists():
        print("first server boot to let Paper fetch and patch the vanilla jar", flush=True)
        server.start(gp_jar=None)
        server.stop()
    print(f"setup complete for MC {mc} in {env.HOME}")
