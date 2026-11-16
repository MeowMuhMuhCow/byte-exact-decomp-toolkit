# Step 7 — Relational Siblings, Transplants, Rosetta, and Mechanical Mutators (`07_mutator_schwestern/`)

Tools for finding structural siblings along two complementary similarity metrics (`Metric A` instruction sequence and `Metric B` calls/globals/opcode profile), transplanting matched sibling bodies mechanically (`transplant.py`), querying 3-instruction normalized assembly windows across all matched functions (`rsuch.py` / `ros.py`), matching unoptimized demo/debug partners (`demo_zuordnung.py`), and running local expression/type beam search (`mutator.py`, `vmasch.py`, `operatoren.py`, `beam.py`).

## Included Scripts

| Script | Purpose |
|---|---|
| `aehnlich.py` | **Metric A:** Ranks matched sibling templates by 3-gram Jaccard pre-filter + `SequenceMatcher` ratio on normalized instruction sequences. |
| `aehnlich_b.py` | **Metric B:** Ranks matched sibling templates by `0.4 * Jaccard(calls) + 0.3 * Jaccard(globals) + 0.3 * Cosine(opcode_histogram)`. |
| `transplant.py` | Aligns donor and target assembly, builds a constant/address substitution table, transplants the C body, and verifies under the ratchet. |
| `rsuch.py` / `ros.py` | **Rosetta:** Regex search over normalized instruction windows (`J`, `[S]`, `ds:A`, `I`) across all matched functions in `orig.tsv`. |
| `demo_zuordnung.py` | Pairs optimized target functions with unoptimized demo/debug build functions. |
| `mutator.py` / `vmasch.py` | Generates `.VT` multi-site variant templates (`//?M00 ... //| ... //.`) and evaluates combinations in batch. |
| `operatoren.py` / `beam.py` | AST/token mutation operators (integer widths, commutative flips, declaration order, block scopes, volatile base loads) and beam search runner. |
