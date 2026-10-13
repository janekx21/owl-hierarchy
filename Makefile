.PHONY: build

build:
	./robot merge --input ./pizza_fixed.ofn reason --reasoner elk filter --term 'http://www.co-ode.org/ontologies/pizza/pizza.owl#American' --select "self parents" convert --output tmp.json && cat tmp.json | python3 obo2tex.py | tee graph.tex
