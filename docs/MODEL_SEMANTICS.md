# Model semantics v1

A model consists of a processor domain n, fixed nonempty vertices V, simple
undirected edges E and immutable Boolean edge expressions. Processor variables
are one-based. State strings use x1 first, xn last. All input bit values are strict
integers 0/1; strings contain exactly n binary digits. Processor counts are 1..64.

Expressions use const(bool), var(index), not(arg), and(args), or(args). AND/OR have
at least two operands; helper builders collapse zero/one-operand constructions to
identities or their argument. No textual expression language or executable model
hooks exist. JSON has strict fields; duplicate keys, nonfinite values, unknown
operators, invalid variable domains and unsupported topology are rejected.
Limits: 10 MB JSON, 10,000 vertices, 50,000 edges, 10,000 nodes / 64 depth per edge AST.
Schema structural validation is followed by Python semantic validation for endpoint
membership, parallel pairs, edge-ID uniqueness, variable domains and resource limits.

Activation includes exactly predicates evaluating true. Connectivity starts with
every vertex, even if it has no active incidence. A singleton is operational for
all processor states. Empty graphs are invalid. Self-loops/parallel input edges are
unsupported; contraction explicitly merges parallel predicates using OR and drops
internal loops under its separately checked connectivity obligation.

Mode selectors must be mutually exclusive and exhaustive over every Boolean state.
This is validated by finite enumeration for n<=12. Larger conditioned models are
rejected as not checked, rather than silently treating sampled partition coverage
as complete. Eq (2) requires equal vertex sets AND equal edge-ID/incidence mappings;
list order alone is insufficient. Automatic alignment uses unit spanning-tree
attachments and zero edges and requires connected underlying auxiliary graphs.
General standalone GL inputs may have disconnected underlying graphs.

Tree complexity `tree-binary-v1` counts each n-ary AND/OR as arity-1 binary
operations; each NOT occurrence counts once. DAG nodes report distinct shared
subexpressions separately. Paper metrics count literal final printed formulas.
Candidate metrics state whether `local-v1` simplification was applied. CPU timing
and memory are separate measurements and cannot be inferred from operation counts.

Exact default checks cover 2^n states for n<=12, first counterexample in lexicographic
state order. NOT_CHECKED, COUNTEREXAMPLE and EXHAUSTIVE_PASS are distinct.
Only AAIT fixed published recipient examples explicitly enumerate n=14; no general
n>12 scalable symbolic checker is claimed. The BDD backend constructs a finite
truth table first; no polynomial scalability claim is made.

Exact reliability weights operational states by independent working probabilities.
Known joint distributions and common-cause mixtures have separate APIs. Wilson
intervals describe Monte Carlo binomial sampling uncertainty at a stated law and
sample count, not uncertain source semantics, dependency-model uncertainty or SLA.

