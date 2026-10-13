# owl-hierarchy

You will have to install "robot" the obo utility and python3.

Build

```
make build
```

Then inside some latex document:

```
input{graph}
```

<img width="164" height="151" alt="image" src="https://github.com/user-attachments/assets/b0db7877-52ba-4359-8070-2054b5f9cd29" />



Robot command explained
```bash
./robot \
  merge --input ./pizza_fixed.ofn \                                      # Load ontology
  reason --reasoner elk \                                                # Materialize 
  filter \
    --term 'http://www.co-ode.org/ontologies/pizza/pizza.owl#American' \ # Filter for one term
    --select "self parents" \                                            # Include the term and all parents
  convert --output tmp.json && \                                         # Output as obo json
cat tmp.json | python3 obo2tex.py | tee graph.tex                        # Create the latex out of that
```
