# Configuration reference

`run_pipeline.py` reads one YAML file with two top-level keys:

| Key | Type | Required | Description |
|---|---|---|---|
| `defaults` | mapping | no | Options applied to every job. |
| `jobs` | list of mappings | **yes** | One entry per pipeline run. |

Every option in the tables below can be set in `defaults` **and** per job. A job value overrides the
default. Mappings (`obo2tex`, `extra_args`, `steps`, `env`) are merged key by key, so a job can change
a single flag without repeating the others. Unknown keys are rejected, which catches typos.
Relative paths are resolved from the directory you start the script in.

## What a job runs

```
[ROBOT, one call]  merge -> (custom) -> reason -> (custom) -> filter -> (custom) -> convert --output <tmp>/tmp.json
[obo2tex.py]       reads tmp.json on stdin, writes LaTeX to stdout -> written to `output` and echoed (like `tee`)
```

`tmp.json` lives in a fresh folder inside the system temp directory and is deleted afterwards
(unless `--keep-tmp`). The `filter` step is only run if `filter_terms` is non-empty.

## Job options

| Key | Type | Default | Description | Example |
|---|---|---|---|---|
| `name` | string | `job<N>` (position in list) | Name used in logs and for `--job`. Also the default output file name. | `american` |
| `input` | string or list of strings | – (**required** unless `obo2tex.sty: true`) | Ontology file(s). Each becomes a `--input` of `robot merge`. | `./pizza_fixed.ofn` |
| `filter_terms` | list of strings | `[]` (no `filter` step) | Term IRIs. Each becomes a `--term` of `robot filter`. | `["http://www.co-ode.org/ontologies/pizza/pizza.owl#American"]` |
| `output` | string | `<name>.tex` | File the obo2tex output is written to. Parent folders are created. | `out/graph.tex` |

## Shared options (usable in `defaults` and in jobs)

### ROBOT installation

| Key | Type | Default | Description | Example |
|---|---|---|---|---|
| `robot_version` | string | `"1.9.11"` | ROBOT release to use. A leading `v` is allowed. If missing, `robot.jar` is downloaded from `https://github.com/ontodev/robot/releases/download/v<version>/robot.jar`. Quote it so YAML does not read it as a number. | `"1.9.11"` |
| `robot_state_dir` | string or null | `null` | Base folder for downloads. `null` = the system state folder (Linux: `$XDG_STATE_HOME` or `~/.local/state`; macOS: `~/Library/Application Support`; Windows: `%LOCALAPPDATA%`), with `robot-pipeline/` appended. The jar ends up in `<dir>/robot/v<version>/robot.jar`. | `~/.cache/my-robots` |
| `robot` | string, list, or null | `null` | Use this command instead of the downloaded jar (nothing is installed; `robot_version`, `java` and `java_args` are ignored). | `"/usr/local/bin/robot"` |
| `java` | string | `"java"` | Java executable used to run the jar. | `"/usr/lib/jvm/java-17/bin/java"` |
| `java_args` | string or list | `[]` | JVM options placed before `-jar`. | `["-Xmx4G"]` |
| `env` | mapping string → string | `{}` | Extra environment variables for all subprocesses. | `{ LC_ALL: C.UTF-8 }` |

### ROBOT pipeline

| Key | Type | Default | Description | Example |
|---|---|---|---|---|
| `reasoner` | string | `"elk"` | One of `elk`, `hermit` (HermiT), `jfact` (JFact), `whelk` (Whelk), `emr` (Expression Materializing Reasoner), `structural` (Structural Reasoner), or `none` to skip `robot reason`. | `hermit` |
| `select` | string or list of strings | `"self parents"` | `--select` of `robot filter`. A list is joined with spaces. See <https://robot.obolibrary.org/filter>. | `"self descendants"` |
| `extra_args` | mapping | all lists empty | Extra arguments appended to a command (see below). | see below |
| `steps` | mapping | all lists empty | Extra ROBOT steps inserted between the built-in ones (see below). | see below |

#### `extra_args`

Keys: `merge`, `reason`, `filter`, `convert`, `obo2tex`. Each value is a **list of strings** or a
**single string** (split shell-style). They are appended to that command.

```yaml
extra_args:
  reason: ["--axiom-generators", "SubClass EquivalentClass"]
  filter: "--preserve-structure false"
  convert: ["--format", "json"]
  obo2tex: []
```

#### `steps`

Keys: `before_merge`, `after_merge`, `after_reason`, `after_filter`. Each value is a **list** whose
items are either a string (`"remove --select imports"`) or a list of strings (`["relax"]`). Each item
is a complete ROBOT command with its options and is chained into the same ROBOT call.

```yaml
steps:
  after_merge:  ["remove --select imports"]
  after_reason: [["relax"]]
  after_filter: ["reduce --reasoner elk"]
```

### obo2tex

| Key | Type | Default | Description | Example |
|---|---|---|---|---|
| `python` | string or list | `"python3"` | Interpreter used to run the script. | `"python3.12"` |
| `obo2tex_script` | string | `"obo2tex.py"` | Path to `obo2tex.py`. | `"tools/obo2tex.py"` |
| `obo2tex` | mapping | all `false` | Flags of `obo2tex.py` (below). Values must be booleans. | see below |

| `obo2tex` key | Default | Passes | Effect |
|---|---|---|---|
| `standalone` | `false` | `--standalone` | Wrap output in a complete compilable document. |
| `sty` | `false` | `--sty` | Print only the macros (`obohierarchy.sty`). Reads no input, so the ROBOT steps are **skipped** and `input` is not needed. |
| `no_macros` | `false` | `--no-macros` | Omit the macro block (use with `\usepackage{obohierarchy}`). |
| `no_root` | `false` | `--no-root` | Do not add an `owl:Thing` root above the top-level classes. |

Any further flag can go in `extra_args.obo2tex`.

## Command line

```
run_pipeline.py CONFIG [--job NAME]... [--dry-run] [--install-only] [--keep-tmp]
```

| Flag | Effect |
|---|---|
| `--job NAME` | Run only the named job(s); repeatable. |
| `--dry-run` | Print the commands (and the download) without running anything. |
| `--install-only` | Download the ROBOT version(s) the config names, then exit. |
| `--keep-tmp` | Keep the temporary folder with `tmp.json`. |

Progress and commands are logged to **stderr**; the LaTeX is echoed to **stdout**, so
`run_pipeline.py cfg.yaml > all.tex` keeps the log on screen.

## Complete example

```yaml
defaults:
  robot_version: "1.9.11"
  java_args: ["-Xmx4G"]
  reasoner: elk
  obo2tex:
    no_root: true

jobs:
  - name: american
    input: ./pizza_fixed.ofn
    filter_terms:
      - http://www.co-ode.org/ontologies/pizza/pizza.owl#American
    output: graph.tex

  - name: margherita
    input: [./pizza_fixed.ofn]
    reasoner: hermit
    select: "self descendants"
    filter_terms:
      - http://www.co-ode.org/ontologies/pizza/pizza.owl#Margherita
    output: out/margherita.tex
    obo2tex: { standalone: true }
    steps:
      after_merge: ["remove --select imports"]

  - name: macros
    output: obohierarchy.sty
    obo2tex: { sty: true }
```
