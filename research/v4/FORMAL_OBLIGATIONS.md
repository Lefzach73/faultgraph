# Boolean chain-summary argument and implementation obligations

Every statement below concerns static all-terminal connectivity with all original
vertices required. Predicates may be correlated and nonmonotone functions of the
same processor vector. It does not concern temporal reliability or service SLA.

For a path u=v0,v1,...,vk=v with distinct internal degree-two vertices, consider a
fixed processor assignment. If two path edges fail, choose consecutive failed
edges ei,ej. The nonempty segment vi,...,v(j-1) contains required internal
vertices and has no connection to either endpoint or the outside graph. The
original system is disconnected. Therefore A ('at most one failed path edge')
is a necessary global obligation, regardless of external endpoint connectivity.

If no path edge fails, every internal vertex joins both endpoints and the path
acts as an active u-v edge. If exactly one fails, the path divides into two
pieces, each attached to one endpoint (one piece can be endpoint-only). There is
no orphaned internal vertex, and no path connection between the endpoints.
Thus, conditional on A, replacing the path by B=AND(f_i) preserves connectivity.
Any already-present u-v predicate is ORed with B. Keep A as a global conjunction.

The recurrence in PLAN.md follows induction on the number of edges. For f_j=true,
at-most-one-failure remains A_(j-1); for f_j=false, it requires B_(j-1) (zero prior
failures). `(A_(j-1) AND f_j) OR B_(j-1)` expresses exactly those cases because
B_(j-1) implies A_(j-1). Update B only after computing the new A.

For a closed chain returning to u, zero or one missing edge leaves a connected
cycle/path including u and every internal vertex; two missing edges isolate a
nonempty segment away from u. Keep A, remove the internal vertices, and add no
self-loop. Pin one vertex so the reduced graph is never empty.

Maximal chain interiors are disjoint. Applying the rule to every chain and
conjoining all A factors therefore preserves the single operational indicator.
Shared processor variables do not invalidate this pointwise reasoning, but do
invalidate multiplying marginal probabilities of the factors in general.

This is an explicit argument using established reductions; it is not a novelty
claim or a machine-checked universal implementation theorem. Required controls:
- a graph with an always-active external endpoint route and two failed chain
  edges must expose a missing-A mutant;
- exhaustive small graphs with shared and negated predicates;
- pure cycles, singletons, disconnected graphs and graphs with no degree-two
  vertex; retained-root behavior and parallel macroedge OR;
- native-controller oracle and independent SMT equivalence for every accepted
  prospective output; UNKNOWN is not acceptance;
- no runtime/truth-based chain selection and no post-freeze heuristic changes.
