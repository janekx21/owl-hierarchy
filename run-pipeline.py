#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml"]
# ///
"""
Run a ROBOT -> obo2tex pipeline for every job described in a YAML file.

Equivalent to running, per job:

  java -jar robot.jar merge --input onto.ofn reason --reasoner elk \
      filter --term <IRI> --select "self parents" \
      convert --output /tmp/xyz/tmp.json \
  && cat /tmp/xyz/tmp.json | python3 obo2tex.py | tee graph.tex

ROBOT itself is downloaded on demand (version from the YAML) into the
system's state folder. See CONFIG.md for the config file format.

Usage:
  ./run_pipeline.py config.yaml
  ./run_pipeline.py config.yaml --job american --dry-run
  ./run_pipeline.py config.yaml --install-only
"""
import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required. Run via `uv run run_pipeline.py ...` (see flake.nix).")

REASONERS = {
    "elk": "ELK",
    "hermit": "HermiT",
    "jfact": "JFact",
    "whelk": "Whelk",
    "emr": "Expression Materializing Reasoner",
    "structural": "Structural Reasoner",
}

ROBOT_URL = "https://github.com/ontodev/robot/releases/download/v{version}/robot.jar"

# Every option a job understands, with its default. Keep CONFIG.md in sync.
DEFAULTS = {
    "robot_version": "1.9.11",
    "robot_state_dir": None,
    "robot": None,
    "java": "java",
    "java_args": [],
    "python": "python3",
    "obo2tex_script": "obo2tex.py",
    "reasoner": "elk",
    "select": "self parents",
    "env": {},
    "obo2tex": {"standalone": False, "sty": False, "no_macros": False, "no_root": False},
    "extra_args": {"merge": [], "reason": [], "filter": [], "convert": [], "obo2tex": []},
    "steps": {"before_merge": [], "after_merge": [], "after_reason": [], "after_filter": []},
}
# Options that only make sense per job (no default)
JOB_ONLY_KEYS = {"name", "input", "filter_terms", "output"}


# ----------------------------------------------------------------- helpers
def log(msg, level="INFO"):
    print(f"[{time.strftime('%H:%M:%S')}] {level:<5} {msg}", file=sys.stderr, flush=True)


def as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def as_args(value):
    """'--foo bar' -> ['--foo','bar'];  ['--foo','bar'] stays as is."""
    if value is None:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    return [str(v) for v in value]


def deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def fmt_cmd(cmd):
    return " ".join(shlex.quote(str(c)) for c in cmd)


def check_keys(d, allowed, where):
    unknown = set(d) - set(allowed)
    if unknown:
        raise ValueError(f"unknown key(s) in {where}: {', '.join(sorted(unknown))} "
                         f"(allowed: {', '.join(sorted(allowed))})")


def validate(job, where):
    check_keys(job, set(DEFAULTS) | JOB_ONLY_KEYS, where)
    for key in ("obo2tex", "extra_args", "steps", "env"):
        if not isinstance(job.get(key), dict):
            raise ValueError(f"'{key}' in {where} must be a mapping")
    check_keys(job["obo2tex"], DEFAULTS["obo2tex"], f"{where}.obo2tex")
    check_keys(job["extra_args"], DEFAULTS["extra_args"], f"{where}.extra_args")
    check_keys(job["steps"], DEFAULTS["steps"], f"{where}.steps")
    for k, v in job["obo2tex"].items():
        if not isinstance(v, bool):
            raise ValueError(f"{where}.obo2tex.{k} must be true or false, got {v!r}")


# ----------------------------------------------------------------- ROBOT install
def state_dir(job):
    if job.get("robot_state_dir"):
        return Path(job["robot_state_dir"]).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "robot-pipeline"


def robot_jar_path(job):
    version = str(job["robot_version"]).lstrip("vV")
    return state_dir(job) / "robot" / f"v{version}" / "robot.jar", version


def install_robot(job, dry=False):
    """Make sure robot.jar for job['robot_version'] exists locally; return its path."""
    jar, version = robot_jar_path(job)
    if jar.exists():
        log(f"ROBOT v{version} already installed: {jar}")
        return jar
    url = ROBOT_URL.format(version=version)
    if dry:
        log(f"(dry-run) would download {url} -> {jar}")
        return jar

    log(f"Installing ROBOT v{version}: {url}")
    jar.parent.mkdir(parents=True, exist_ok=True)
    part = jar.with_suffix(".jar.part")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(part, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done, next_report = 0, 0.25
            while chunk := resp.read(1 << 16):
                out.write(chunk)
                done += len(chunk)
                if total and done / total >= next_report:
                    log(f"  downloaded {done / 1e6:.1f}/{total / 1e6:.1f} MB ({done * 100 // total}%)")
                    next_report += 0.25
        with open(part, "rb") as fh:
            if fh.read(2) != b"PK":
                raise RuntimeError("downloaded file is not a valid jar/zip")
        part.replace(jar)  # atomic: a half-finished download is never mistaken for a jar
    except Exception as e:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"could not install ROBOT v{version} from {url}: {e}") from e
    log(f"Installed ROBOT v{version} -> {jar}")
    return jar


def robot_command(job, dry):
    """Command prefix used to invoke ROBOT."""
    if job.get("robot"):  # explicit override, nothing is installed
        return as_args(job["robot"])
    jar = install_robot(job, dry)
    return [job["java"], *as_args(job["java_args"]), "-jar", str(jar)]


# ----------------------------------------------------------------- pipeline
def build_robot_steps(job, json_path):
    """Return list of (label, [robot args]) for the ROBOT part of the pipeline."""
    extra, extra_steps = job["extra_args"], job["steps"]
    steps = []

    def add_custom(key):
        for i, s in enumerate(as_list(extra_steps.get(key))):
            args = as_args(s)
            if args:
                steps.append((f"custom:{key}[{i}] ({args[0]})", args))

    add_custom("before_merge")

    inputs = as_list(job.get("input"))
    if not inputs:
        raise ValueError("job has no 'input' ontology")
    merge = ["merge"]
    for i in inputs:
        merge += ["--input", str(i)]
    steps.append(("merge", merge + as_args(extra.get("merge"))))
    add_custom("after_merge")

    reasoner = job.get("reasoner")
    if reasoner not in (None, False, "none"):
        reasoner = str(reasoner).strip().lower()
        if reasoner not in REASONERS:
            raise ValueError(f"unknown reasoner '{reasoner}'. Choose from: {', '.join(REASONERS)}")
        steps.append((f"reason ({REASONERS[reasoner]})",
                      ["reason", "--reasoner", reasoner] + as_args(extra.get("reason"))))
    add_custom("after_reason")

    terms = as_list(job.get("filter_terms"))
    if terms:
        flt = ["filter"]
        for t in terms:
            flt += ["--term", str(t)]
        select = job.get("select")
        if isinstance(select, (list, tuple)):
            select = " ".join(select)
        if select:
            flt += ["--select", str(select)]
        steps.append(("filter", flt + as_args(extra.get("filter"))))
    add_custom("after_filter")

    steps.append(("convert", ["convert"] + as_args(extra.get("convert")) + ["--output", json_path]))
    return steps


def obo2tex_command(job):
    o = job["obo2tex"]
    flags = [f"--{k.replace('_', '-')}" for k in ("standalone", "sty", "no_macros", "no_root") if o.get(k)]
    return as_args(job["python"]) + [str(job["obo2tex_script"])] + flags + as_args(job["extra_args"].get("obo2tex"))


def run(cmd, env, dry, stdin=None, capture=False):
    log(f"$ {fmt_cmd(cmd)}", "CMD")
    if dry:
        return ""
    try:
        res = subprocess.run(cmd, env=env, stdin=stdin,
                             stdout=subprocess.PIPE if capture else None,
                             stderr=None, text=capture)
    except FileNotFoundError:
        raise RuntimeError(f"executable not found: {cmd[0]} (is it installed and on PATH?)")
    if res.returncode != 0:
        raise RuntimeError(f"command failed with exit code {res.returncode}: {cmd[0]}")
    return res.stdout


def run_job(name, job, dry, keep_tmp):
    env = {**os.environ, **{k: str(v) for k, v in job["env"].items()}}
    sty_only = job["obo2tex"]["sty"]  # --sty reads no input: ROBOT is skipped entirely
    if sty_only:
        log("obo2tex.sty is set: ROBOT steps are skipped, only the macro file is generated")

    tmpdir = tempfile.mkdtemp(prefix=f"robot_{name}_")  # inside the system temp folder
    json_path = os.path.join(tmpdir, "tmp.json")
    steps = [] if sty_only else build_robot_steps(job, json_path)
    total = len(steps) + 1  # +1 for obo2tex
    obo_cmd = obo2tex_command(job)

    log(f"=== Job '{name}' | {total} pipeline steps | tmp: {tmpdir}")
    for i, (label, _) in enumerate(steps, 1):
        log(f"    {i}/{total} {label}")
    log(f"    {total}/{total} obo2tex -> {job['output']}")

    try:
        t0 = time.time()
        if steps:
            robot = robot_command(job, dry)
            log(f"--- Steps 1-{len(steps)}/{total}: ROBOT ({' -> '.join(s[0] for s in steps)})")
            cmd = list(robot)
            for _, args in steps:
                cmd += args
            run(cmd, env, dry)

        log(f"--- Step {total}/{total}: obo2tex")
        if dry:
            run(obo_cmd, env, True)
            log(f"(dry-run) would write {job['output']}")
        else:
            if sty_only:
                tex = run(obo_cmd, env, False, capture=True)
            else:
                with open(json_path, "rb") as fh:
                    tex = run(obo_cmd, env, False, stdin=fh, capture=True)
            out = Path(job["output"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(tex)
            sys.stdout.write(tex if tex.endswith("\n") else tex + "\n")  # the "tee" part
            log(f"Wrote {out}")
        log(f"=== Job '{name}' done in {time.time() - t0:.1f}s")
    finally:
        if keep_tmp:
            log(f"Keeping temp dir {tmpdir}")
        else:
            shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("config", help="YAML config file")
    ap.add_argument("--job", action="append", help="only run job(s) with this name (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="print commands without running them")
    ap.add_argument("--install-only", action="store_true",
                    help="only download the ROBOT version(s) named in the config, then exit")
    ap.add_argument("--keep-tmp", action="store_true", help="do not delete temporary files")
    args = ap.parse_args()

    with open(args.config) as fh:
        cfg = yaml.safe_load(fh) or {}
    check_keys(cfg, {"defaults", "jobs"}, "top level")

    base = deep_merge(DEFAULTS, cfg.get("defaults"))
    jobs = cfg.get("jobs")
    if not jobs:
        sys.exit("config needs a non-empty 'jobs' list")

    if args.install_only:
        seen = set()
        for idx, j in enumerate(jobs, 1):
            job = deep_merge(base, j)
            jar, _ = robot_jar_path(job)
            if jar not in seen and not job.get("robot"):
                seen.add(jar)
                install_robot(job, args.dry_run)
        return

    ran = failed = 0
    for idx, j in enumerate(jobs, 1):
        name = str(j.get("name", f"job{idx}"))
        if args.job and name not in args.job:
            continue
        ran += 1
        log(f"##### Job {idx}/{len(jobs)}: {name}")
        try:
            job = deep_merge(base, j)
            validate(job, f"job '{name}'")
            job.setdefault("output", f"{name}.tex")
            run_job(name, job, args.dry_run, args.keep_tmp)
        except Exception as e:  # keep going with the other jobs
            failed += 1
            log(f"Job '{name}' FAILED: {e}", "ERROR")
    log(f"Finished. {ran - failed} ok, {failed} failed.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
