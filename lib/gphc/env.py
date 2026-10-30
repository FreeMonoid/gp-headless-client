"""Locations, pins, tool discovery and small process helpers. Everything lives under GPHC_HOME (default ~/.gphc)."""
import functools, json, os, platform, re, signal, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOME = Path(os.environ.get("GPHC_HOME", "~/.gphc")).expanduser().resolve()
DL = HOME / "dl"
CLIENT = HOME / "client"          # HeadlessMc home: -Duser.home + XDG dirs point here
RUNS = HOME / "runs"
PINS = json.loads((REPO / "pins.json").read_text())


def mc_pins(mc):
    try:
        return PINS["mc"][mc]
    except KeyError:
        sys.exit(f"no pins for MC {mc}; known: {', '.join(PINS['mc'])}")


def default_mc():
    return os.environ.get("GPHC_MC", PINS["default_mc"])


def java_override(major):
    return os.environ.get(f"GPHC_JAVA_{major}")


def jre_pin(major):
    """This machine's pinned JRE for Java `major`."""
    os_name = {"Darwin": "mac", "Linux": "linux"}.get(platform.system())
    arch = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x64", "amd64": "x64"}.get(platform.machine().lower())
    try:
        return PINS["java"][str(major)][f"{os_name}-{arch}"]
    except KeyError:
        sys.exit(f"no Java {major} pinned for {platform.system()} {platform.machine()}; set GPHC_JAVA_{major} to a Java {major} home")


def jre_dir(major):
    """The Java home `setup` unpacks the pinned JRE to, named after its archive so a bumped pin installs afresh."""
    return HOME / "java" / jre_pin(major)["url"].rsplit("/", 1)[1].removesuffix(".tar.gz")


@functools.cache
def java_home(mc):
    """GPHC_JAVA_<major> if set, else the pinned JRE. HeadlessMc only launches a client on the exact major version
    the MC manifest names, so HeadlessMc, the client and Paper all run on this one."""
    major = mc_pins(mc)["java"]
    override = java_override(major)
    if not override:
        if not jre_dir(major).exists():
            sys.exit(f"Java {major} for MC {mc} is not installed; run `gphc setup --mc {mc}`")
        return jre_dir(major)
    j = Path(override) / "bin" / "java"
    if not j.exists():
        sys.exit(f"GPHC_JAVA_{major}={override} has no bin/java")
    out = subprocess.run([j, "-XshowSettings:properties", "-version"], capture_output=True, text=True).stderr
    version, home = re.search(r'version "(\d+)', out), re.search(r"java\.home = (.+)", out)
    if not (version and home):
        sys.exit(f"GPHC_JAVA_{major}={override}: could not read its version:\n{out}")
    if int(version[1]) != major:
        sys.exit(f"GPHC_JAVA_{major}={override} is Java {version[1]}")
    # The JVM's own java.home: a wrapper such as macOS /usr/bin/java under JAVA_HOME=/usr hangs HeadlessMc
    return Path(home[1].strip())


def java(mc):
    return str(java_home(mc) / "bin" / "java")


def minecraft_dir():
    """Where the launcher puts .minecraft when user.home is CLIENT (POSIX only: we rely on process groups)."""
    if platform.system() == "Darwin":
        return CLIENT / "Library" / "Application Support" / "minecraft"
    return CLIENT / ".minecraft"


def game_dir(mc):
    return minecraft_dir() / f"fabric-{mc}"


def server_dir(mc):
    return HOME / "servers" / mc


def hmc_env(mc):
    env, home = dict(os.environ), java_home(mc)
    env.update(
        JAVA_HOME=str(home),
        PATH=f"{home}/bin:{env.get('PATH', '')}",
        XDG_DATA_HOME=str(CLIENT / "data"),
        XDG_CONFIG_HOME=str(CLIENT / "config"),
        XDG_STATE_HOME=str(CLIENT / "state"),
        XDG_CACHE_HOME=str(CLIENT / "cache"),
    )
    return env


def hmc_cmd(mc, *args):
    """HeadlessMc on `mc`'s Java, offered as its only Java so it never looks for (or downloads) another.
    Assets are stubbed (~380 MB of sounds and textures); language files and fonts stay real."""
    return [java(mc), "-Dhmc.jline.enabled=false", f"-Dhmc.java.versions={java_home(mc)}", "-Dhmc.java.download=false",
            "-Dhmc.assets.dummy=true", f"-Duser.home={CLIENT}", "-jar", str(DL / "headlessmc.jar"), *args]


def hmc(mc, *args, **kw):
    """Run a HeadlessMc command to completion."""
    CLIENT.mkdir(parents=True, exist_ok=True)
    return subprocess.run(hmc_cmd(mc, *args), cwd=CLIENT, env=hmc_env(mc), **kw)


def launch_client(mc, log, *args):
    """Start a headless Fabric client in its own process group, logging to `log`."""
    return subprocess.Popen(hmc_cmd(mc, "launch", "--offline", "--headless", *args, "fabric", mc), cwd=CLIENT,
                            env=hmc_env(mc), stdout=open(log, "w"), stderr=subprocess.STDOUT, start_new_session=True)


def read_from(path, pos=0):
    with open(path, errors="replace") as f:
        f.seek(pos)
        return f.read()


def wait_for(log, pattern, proc, timeout, what, pos=0):
    """Poll `log` (from byte `pos`) until `pattern` matches; fail if `proc` exits or `timeout` seconds pass."""
    rx, deadline = re.compile(pattern), time.time() + timeout
    while time.time() < deadline:
        if rx.search(read_from(log, pos)):
            return
        if proc.poll() is not None:
            raise RuntimeError(f"process exited while waiting for {what}; see {log}")
        time.sleep(0.5)
    raise TimeoutError(f"timed out waiting for {what}; see {log}")


def terminate(proc, grace=15):
    """SIGTERM a process group, SIGKILL it if it lingers; fine to call on a process that already exited."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(grace)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
