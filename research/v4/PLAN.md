# v4 preregistration: obligation-preserving chain compilation

2026-10-12. This new trial follows v2's refuted hypothesis and v3's incomplete
cold-construction comparison. Both are preserved. The user explicitly requested
continued research using a workflow. This document precedes candidate code and
new-case performance evaluation. Priority/novelty remain UNESTABLISHED.

## Known foundations and new empirical question

Series/degree-two/polygon-to-chain network reliability reductions are established
prior art (Satyanarayana/Wood, DOI10.1137/0214057; the author-hosted implementation
paper https://resende.info/mauricio/doc/polychain.pdf). BDD construction, dynamic
variable ordering and shared Boolean functions are also established. We do not
claim to invent any of these. Our question is their explicitly guarded Boolean
use with correlated processor predicates in GL models, measured against a
stronger direct-symbolic CUDD connectivity compiler on fresh external cores.

The v3 AIG-to-CUDD path includes an extra representation layer. Add a conventional
baseline that compiles edge expressions directly into CUDD and performs exact
synchronous reachability, stopping only on canonical-function fixed point. Both
that baseline and the candidate use the same manager limits, root choice,
variable order, sifting, export and evaluator. This avoids an intentionally weak
baseline. ABC and the v3 AIG compiler remain measured secondary comparators.

## Mathematical obligation (derived here; not attributed as a paper formula)

For a maximal path of k edges whose internal vertices have degree2, let f_i(x)
be the native edge predicates. Define B = AND_i f_i and A = 'at most one f_i is
false'. A is required because two failed path edges strand at least one required
internal vertex, even if the endpoints connect outside the path. If A holds,
all internal vertices attach to at least one endpoint; the endpoints are joined
through the path iff B holds. Replace the path by an edge B, OR with any existing
parallel endpoint predicate, and retain A as a global connectivity obligation.

Compute A/B with Boolean recurrence A0=B0=true;
A_j=(A_{j-1} AND f_j) OR B_{j-1}; B_j=B_{j-1} AND f_j.
The update uses the OLD B. This identity is pointwise and assumes neither
independent edges nor independent processor failures. Shared and negated
predicates are allowed. All global obligations remain conjoined symbolically;
never multiply their probabilities as independent events.

For a closed path returning to the same retained endpoint (including an entire
cycle), A is the all-terminal connectivity condition of the cycle; remove the
internal vertices and retain A, with no self-loop. A single retained vertex has
connectivity true, so the global obligation still matters. For an originally
disconnected topology the result is false. These arguments need independent
implementation checks; they are not a mechanically verified universal theorem.

Root: highest original degree, lexicographic tie break; retain that root as a
boundary even if its degree is2. Other boundaries are exactly degree!=2 vertices.
Extract maximal paths deterministically and in linear graph work; no label,
oracle or runtime-guided selection. Original edge/vertex lineage and A/B
summaries must be retained. Pure degree>=3 graphs are unchanged controls.

## Prospective source scope and selection

Use the same pinned author-maintained Topology Zoo archive, with fresh providers
excluding every v3 provider. The initial whole-network biconnected size filter
provided only one eligible fresh provider; BEFORE candidate coding/evaluation,
we instead define the target as the largest biconnected core per provider.
Choose by largest vertex count, then edge count, then lexicographic IDs. This is
an explicit subsystem study, not a claim about whole-provider availability.

Select the first six alphabetical eligible distinct provider cores with
10<=V<=24,12<=physical E<=32 and logical cycle rank>=2. Exclude all prior evaluated
exact topologies. Do not filter on degree2 counts, compiler output, truth or
runtime. Source metadata/profile inspection precedes freeze, but no optimizer
has been evaluated on these new cases. Retain full original source maps and the
exact chosen core/omitted-vertex mapping. No degree-one/unit-tree wrappers.

Physical parallel links are retained individually in the domain oracle and
combined by OR only in the logical simple-graph encoding. This is pointwise
connectivity-equivalent and must be certified; no physical link is silently
removed. Exclude directed inputs or source self-loops. Keep CC-BY4.0 attribution.

Use single, redundant-pair and shared-controller policies from v3 as documented
hypothetical link rules; the novelty of these rules is NOT claimed. Seeds
7013,8011,9001,10007,11003.90 instances are six core/provider clusters, not90
independent networks. Dataset/software hashes freeze before evaluation.

## Arms, costs and primary hypothesis

Six arms: published native GL; legacy local GL; v3 AIG-to-dynamic-CUDD;
direct symbolic dynamic CUDD; guarded chain-to-direct-CUDD (candidate); ABC resyn2.
Fixed-order CUDD is not a required comparator in this new trial because its
budget fragility was established in v3; all its failures remain archived.
The new candidate must beat the stronger DIRECT baseline, not only the old one.

Primary H-chain: >=3/6 clusters have median WARM construction ratio<=0.80 versus
BOTH direct-symbolic CUDD and v3 AIG-CUDD, exported-query p50<=1.10 of the direct
baseline, and peak RSS<=1.10. All required arms must be certified; missing outputs
make the primary outcome INCONCLUSIVE. Cold import cost is measured separately
and cold total construction is reported, not hidden. This new warm-library
question follows the disclosed v3 startup diagnostic; it is not a relabeled v3 win.

Per arm:30s construction,60s per exact verification query,180s worker envelope,
256MiB CUDD manager limit and100000 manager/export/gate nodes. Limits apply equally.
256 uniform and256 p=.95 query states, five repeats,16 warm-ups; deterministic
arm rotation and fresh sequential workers. Dependencies are imported before warm
construction; every import/startup cost is separately recorded. Graph counts,
retained chain counts, Boolean/BDD sizes, memory, queries and proof costs separate.

Use exact SMT plus independent oracle comparisons; exhaustive n<=12, otherwise
sampling is explicitly supplementary to exact symbolic certification. All
failures and unknowns retained. Bootstrap at six whole-provider/core clusters,
paired seeds/policies, descriptive only. All probability laws use original
processor variables and their documented correlation structure.

A positive result would establish a bounded empirical result, not global
optimality, universal superiority, novelty priority or independent human review.
