"""`gphc run <scenario.py>`: boot server, run the scenario, print a JSON verdict, tear down."""
import json, runpy, shutil, sys, traceback
from datetime import datetime
from pathlib import Path
from . import env
from .api import Test
from .client import Bots
from .server import Server


def run(scenario_path, mc, gp_jar, keep=False):
    ns = runpy.run_path(scenario_path)
    if "run" not in ns:
        sys.exit(f"{scenario_path} defines no run(t)")
    if ns.get("MC") and mc not in ns["MC"]:
        sys.exit(f"{scenario_path} supports MC {ns['MC']}, not {mc}")
    name = Path(scenario_path).stem
    run_dir = env.RUNS / f"{datetime.now():%Y%m%d-%H%M%S}-{name}"
    run_dir.mkdir(parents=True)
    server, bots, t, error = Server(mc), None, None, None
    with open(run_dir / "trace.log", "w") as trace:
        try:
            server.start(gp_jar)
            bots = Bots(mc, server, run_dir)
            t = Test(server, bots, trace)
            ns["run"](t)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            traceback.print_exc(file=trace)
            traceback.print_exc()
        finally:
            if bots:
                bots.kill_all()
            if not keep:
                server.stop()
            if server.log.exists():
                shutil.copy(server.log, run_dir / "server.log")
    checks = t.checks if t else []
    report = {"scenario": name, "mc": mc, "gp_version": server.gp_version, "gp_jar": str(gp_jar),
              "ok": error is None and all(c["ok"] for c in checks), "checks": checks, "error": error,
              "run_dir": str(run_dir)}
    (run_dir / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1
