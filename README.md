# owl-hierarchy

A utility to create .tex file from owl ontology with reasoning.

<img width="164" height="151" alt="image" src="https://github.com/user-attachments/assets/b0db7877-52ba-4359-8070-2054b5f9cd29" />

## Getting Started

Prerequisites: (look at flake.nix)

- python3
- jdk

```sh
chmod +x ./run-pipeline.py
```

### Config

Take a look at [config.md](config.md) or the [example.config.yaml](example.config.yaml) on how to config.

- Create a yaml config file

### Run

```sh
./run-pipeline.py <you-config-file.yaml>
```

## Usage

Then inside some latex document:

```tex
input{<your-output-name>}
```

## Example

Create config.yaml
```yaml
jobs:
  - name: american
    input: ./pizza_fixed.ofn
    filter_terms:
      - http://www.co-ode.org/ontologies/pizza/pizza.owl#American
    output: out/graph.tex
```

Run
```sh
./run-pipeline.py config.yaml
```

Add to tex file
```tex
input{out/graph}
```

Result
<img width="164" height="151" alt="image" src="https://github.com/user-attachments/assets/b0db7877-52ba-4359-8070-2054b5f9cd29" />
