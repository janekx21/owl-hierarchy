#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml"]
# ///
"""
Run a ROBOT -> obo2tex pipeline for every job described in a YAML file.

Equivalent to running, per job:

  ./robot merge --input onto.ofn reason --reasoner elk \
      filter --term <IRI> --select "self parents" \
      convert --output /tmp/xyz/tmp.json \
  && cat /tmp/xyz/tmp.json | python3 obo2tex.py | tee graph.tex

Usage:
  python run_pipeline.py config.yaml
  python run_pipeline.py config.yaml --job american --dry-run
  python run_pipeline.py config.yaml --stepwise      # one ROBOT call per step
"""
import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required:  pip install pyyaml")

REASONERS = {
    "elk": "ELK",
    "hermit": "HermiT",
    "jfact": "JFact",
    "whelk": "Whelk",
    "emr": "Expression Materializing Reasoner",
    "structural": "Structural Reasoner",
}

DEFAULTS = {
    "robot": "./robot",
    "python": "python3",
    "obo2tex": "obo2tex.py",
    "reasoner": "elk",
    "select": "self parents",
    "stepwise": False,
    "env": {},
    # extra args, one list per tool/step
    "extra_args": {"merge": [], "reason": [], "filter": [], "convert": [], "obo2tex": []},
    # additional ROBOT steps injected at certain points (each is a list of args or a string)
    "steps": {"before_merge": [], "after_merge": [], "after_reason": [],
              "after_filter": []},
}


# ----------------------------------------------------------------- helpers
def log(msg, level="INFO"):
    print(f"[{time.strftime('%H:%M:%S')}] {level:<5} {msg}", flush=True)


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
    return " ".join(shlex.quote(c) for c in cmd)


# ----------------------------------------------------------------- pipeline
def build_steps(job, json_path):
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


def run(cmd, env, dry, stdin=None, capture=False):
    log(f"$ {fmt_cmd(cmd)}", "CMD")
    if dry:
        return ""
    res = subprocess.run(cmd, env=env, stdin=stdin,
                         stdout=subprocess.PIPE if capture else None,
                         stderr=None, text=capture)
    if res.returncode != 0:
        raise RuntimeError(f"command failed with exit code {res.returncode}: {cmd[0]}")
    return res.stdout


def run_job(name, job, dry, keep_tmp):
    tmpdir = tempfile.mkdtemp(prefix=f"robot_{name}_")  # lives in the system temp folder
    json_path = os.path.join(tmpdir, "tmp.json")
    env = {**os.environ, **{k: str(v) for k, v in (job.get("env") or {}).items()}}
    robot = as_args(job["robot"])
    steps = build_steps(job, json_path)
    total = len(steps) + 1  # +1 for obo2tex
    stepwise = bool(job.get("stepwise"))

    log(f"=== Job '{name}' | {total} pipeline steps | mode: "
        f"{'stepwise' if stepwise else 'single ROBOT call'} | tmp: {tmpdir}")
    for i, (label, _) in enumerate(steps, 1):
        log(f"    {i}/{total} {label}")
    log(f"    {total}/{total} obo2tex -> {job['output']}")

    try:
        t0 = time.time()
        if stepwise:
            prev = None
            for i, (label, args) in enumerate(steps, 1):
                log(f"--- Step {i}/{total}: {label}")
                last = i == len(steps)
                out = json_path if last else os.path.join(tmpdir, f"step{i}.owl")
                a = list(args)
                if last:
                    cmd = robot + ([ "--input", prev] if prev else []) + a  # convert has --output
                else:
                    cmd = robot + ([ "--input", prev] if prev else []) + a + ["--output", out]
                    prev = out
                run(cmd, env, dry)
                if last:
                    prev = json_path
        else:
            log(f"--- Steps 1-{len(steps)}/{total}: ROBOT ({' -> '.join(s[0] for s in steps)})")
            cmd = list(robot)
            for _, args in steps:
                cmd += args
            run(cmd, env, dry)

        log(f"--- Step {total}/{total}: obo2tex")
        cmd = as_args(job["python"]) + [str(job["obo2tex"])] + as_args(job["extra_args"].get("obo2tex"))
        if dry:
            run(cmd, env, True)
            log(f"(dry-run) would write {job['output']}")
        else:
            with open(json_path, "rb") as fh:
                tex = run(cmd, env, False, stdin=fh, capture=True)
            Path(job["output"]).parent.mkdir(parents=True, exist_ok=True)
            Path(job["output"]).write_text(tex)          # the "tee" part
            print(tex, end="" if tex.endswith("\n") else "\n")
            log(f"Wrote {job['output']}")
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
    ap.add_argument("--stepwise", action="store_true", help="force one ROBOT call per step")
    ap.add_argument("--keep-tmp", action="store_true", help="do not delete temporary files")
    args = ap.parse_args()

    with open(args.config) as fh:
        cfg = yaml.safe_load(fh) or {}

    base = deep_merge(DEFAULTS, cfg.get("defaults"))
    jobs = cfg.get("jobs")
    if not jobs:
        sys.exit("config needs a non-empty 'jobs' list")

    failed = 0
    for idx, j in enumerate(jobs, 1):
        name = str(j.get("name", f"job{idx}"))
        if args.job and name not in args.job:
            continue
        job = deep_merge(base, j)
        if args.stepwise:
            job["stepwise"] = True
        job.setdefault("output", f"{name}.tex")
        log(f"##### Job {idx}/{len(jobs)}: {name}")
        try:
            run_job(name, job, args.dry_run, args.keep_tmp)
        except Exception as e:  # keep going with the other jobs
            failed += 1
            log(f"Job '{name}' FAILED: {e}", "ERROR")
    log(f"Finished. {len(jobs) - failed if not args.job else 'selected'} ok, {failed} failed.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
