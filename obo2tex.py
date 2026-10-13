#!/usr/bin/env python3
"""obo2tex v2: read OBO Graphs JSON on stdin, write a LaTeX class hierarchy to stdout.

The output imitates the class hierarchy view in Protege: gold class icons,
grey expand triangles and dotted connector lines, rooted at owl:Thing. The
tree is built from subclass edges (is_a / subClassOf). A class with several
parents appears under each of them.

Usage:
    cat ontology.json | python obo2tex.py > ontology.tex
    cat ontology.json | python obo2tex.py --standalone > main.tex
    cat ontology.json | python obo2tex.py --no-root > ontology.tex

Fragment output needs \\usepackage{tikz} in the host document; missing
packages are reported with a LaTeX error.
"""
import argparse
import json
import re
import sys
from collections import defaultdict

LATEX_SPECIAL = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
SUBCLASS_PREDS = {"is_a", "subclassof"}

# Connector codes for one indentation column of a row.
BLANK, VLINE, TEE, CORNER = 0, 1, 2, 3


def esc(text):
    return "".join(LATEX_SPECIAL.get(c, c) for c in str(text))


def short_id(iri):
    frag = re.split(r"[#/]", iri.rstrip("/#"))[-1]
    return frag or iri


def is_subclass_pred(pred):
    return short_id(pred).lower() in SUBCLASS_PREDS


def display_name(node):
    return node.get("lbl") or short_id(node["id"])


GUARDS = r"""% --- obo2tex: required packages ---
\providecommand{\oboneed}[2]{\ifdefined#1\else
  \PackageError{obo2tex}{Missing package: #2}{Add \string\usepackage{#2} to your preamble.}\fi}
\oboneed{\tikzset}{tikz}
\oboneed{\foreach}{pgffor}
\oboneed{\pgfmathsetlengthmacro}{pgfmath}
\oboneed{\providecolor}{xcolor}
"""

MACROS = r"""% --- class hierarchy macros (redefine to restyle) ---
\providecommand{\oboslot}{1.1em}      % width of the expand-triangle slot
\providecommand{\oboicon}{0.9em}      % diameter of the class icon
\providecommand{\oborowheight}{1.5em} % height of one tree row
\providecolor{obogold}{RGB}{229,177,0}
\providecolor{obotri}{gray}{0.45}
\providecolor{oboconn}{gray}{0.5}
\tikzset{oboline/.style={dotted,line width=0.6pt,oboconn}}
% \oboclassrow{depth}{connector codes}{is branch 0/1}{label}
% codes per column: 0 blank, 1 vertical, 2 tee, 3 corner
\providecommand{\oboclassrow}[4]{%
  \hbox{\begin{tikzpicture}[baseline=0pt]
    \pgfmathsetlengthmacro{\oboW}{\oboslot+\oboicon}
    \pgfmathsetlengthmacro{\oboh}{\oborowheight/2}
    \pgfmathsetlengthmacro{\obor}{\oboicon/2}
    \useasboundingbox (0,-\oboh) rectangle (0,\oboh);
    \ifnum#1>0
      \foreach \c [count=\k from 0] in {#2} {%
        \pgfmathsetlengthmacro{\oboxc}{\k*\oboW+\oboslot+\oboicon/2}%
        \ifcase\c\relax
        \or \draw[oboline] (\oboxc,\oboh) -- (\oboxc,-\oboh);%
        \or \draw[oboline] (\oboxc,\oboh) -- (\oboxc,-\oboh);%
            \ifnum#3=1 \pgfmathsetlengthmacro{\oboxe}{(\k+1)*\oboW+0.15*\oboslot}%
            \else \pgfmathsetlengthmacro{\oboxe}{(\k+1)*\oboW+\oboslot}\fi
            \draw[oboline] (\oboxc,0) -- (\oboxe,0);%
        \or \draw[oboline] (\oboxc,\oboh) -- (\oboxc,0);%
            \ifnum#3=1 \pgfmathsetlengthmacro{\oboxe}{(\k+1)*\oboW+0.15*\oboslot}%
            \else \pgfmathsetlengthmacro{\oboxe}{(\k+1)*\oboW+\oboslot}\fi
            \draw[oboline] (\oboxc,0) -- (\oboxe,0);%
        \fi
      }%
    \fi
    \pgfmathsetlengthmacro{\oboxd}{#1*\oboW+\oboslot+\oboicon/2}%
    \ifnum#3=1
      \pgfmathsetlengthmacro{\oboxt}{#1*\oboW+\oboslot/2}%
      \path[fill=obotri] (\oboxt-0.28em,0.12em) -- (\oboxt+0.28em,0.12em)
        -- (\oboxt,-0.18em) -- cycle;
      \draw[oboline] (\oboxd,-\obor) -- (\oboxd,-\oboh);
    \fi
    \filldraw[fill=obogold,draw=obogold!65!black,line width=0.4pt] (\oboxd,0) circle (\obor);
    \pgfmathsetlengthmacro{\oboxl}{(#1+1)*\oboW}%
    \node[anchor=west,inner xsep=0.3em,inner ysep=0pt,font=\sffamily\small] at (\oboxl,0) {#4};
  \end{tikzpicture}}\vskip0pt}
"""


class Graph:
    def __init__(self, data):
        self.id = data.get("id", "graph")
        self.meta = data.get("meta") or {}
        self.classes = {n["id"]: n for n in data.get("nodes", [])
                        if (n.get("type") or "CLASS") == "CLASS"}
        self.children = defaultdict(list)
        self.has_parent = set()
        for e in data.get("edges", []):
            if (is_subclass_pred(e["pred"]) and e["sub"] in self.classes
                    and e["obj"] in self.classes and e["sub"] != e["obj"]):
                self.children[e["obj"]].append(e["sub"])
                self.has_parent.add(e["sub"])

    def sorted_ids(self, ids):
        return sorted(set(ids), key=lambda i: display_name(self.classes[i]).lower())

    def roots(self):
        roots = [i for i in self.classes if i not in self.has_parent]
        # Classes only reachable through cycles would otherwise vanish.
        seen = set()
        for r in roots:
            self._reach(r, seen)
        for i in self.sorted_ids(self.classes):
            if i not in seen:
                roots.append(i)
                self._reach(i, seen)
        return self.sorted_ids(roots)

    def _reach(self, nid, seen):
        stack = [nid]
        while stack:
            cur = stack.pop()
            if cur not in seen:
                seen.add(cur)
                stack.extend(self.children[cur])


def row(prefix, branch, label):
    return r"\oboclassrow{%d}{%s}{%d}{%s}" % (
        len(prefix), ",".join(map(str, prefix)), 1 if branch else 0, label)


def child_prefixes(prefix, count):
    """Prefixes for `count` children of a node whose own row prefix is `prefix`."""
    base = list(prefix)
    if base:  # the parent's elbow column becomes a pass-through column
        base[-1] = VLINE if base[-1] == TEE else BLANK
    return [base + [CORNER if i == count - 1 else TEE] for i in range(count)]


def render_tree(g, nid, prefix, path, lines):
    kids = [k for k in g.sorted_ids(g.children[nid]) if k not in path]  # cycle guard
    lines.append(row(prefix, kids, esc(display_name(g.classes[nid]))))
    for k, p in zip(kids, child_prefixes(prefix, len(kids))):
        render_tree(g, k, p, path | {nid}, lines)


def render_graph(g, with_root):
    lines = [r"\begingroup\offinterlineskip"]
    roots = g.roots()
    if with_root:
        lines.append(row([], bool(roots), "owl:Thing"))
        prefixes = child_prefixes([], len(roots))
    else:
        prefixes = [[] for _ in roots]
    for r, p in zip(roots, prefixes):
        render_tree(g, r, p, frozenset(), lines)
    lines.append(r"\endgroup")
    return "\n".join(lines)


STY_HEADER = r"""\NeedsTeXFormat{LaTeX2e}
\ProvidesPackage{obohierarchy}[2026/10/13 OBO class hierarchy macros]
\RequirePackage{xcolor}
\RequirePackage{tikz}
"""


PREAMBLE = r"""\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{tikz}
\begin{document}
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--standalone", action="store_true",
                    help="wrap output in a complete compilable document")
    ap.add_argument("--sty", action="store_true",
                    help="print only the macros as obohierarchy.sty (reads no input)")
    ap.add_argument("--no-macros", action="store_true",
                    help="omit the macro block (use with \\usepackage{obohierarchy})")
    ap.add_argument("--no-root", action="store_true",
                    help="do not add an owl:Thing root above the top-level classes")
    args = ap.parse_args()

    if args.sty:
        sys.stdout.write(STY_HEADER + MACROS)
        return

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        sys.exit("obo2tex: invalid JSON on stdin: %s" % e)

    body = "\n\n\\medskip\n\n".join(render_graph(Graph(g), not args.no_root)
                       for g in data.get("graphs", []))
    out = ("" if args.no_macros else GUARDS + "\n" + MACROS + "\n") + body + "\n"
    if args.standalone:
        out = PREAMBLE + "\n" + out + "\\end{document}\n"
    sys.stdout.write(out)


if __name__ == "__main__":
    main()
