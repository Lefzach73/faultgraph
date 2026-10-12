# Bounded systematic prior-art audit v1 (2026-10-12)

This is a scoped, reproducible search, not an exhaustive bibliometric review or
proof of novelty. Sources were screened through publisher/author/implementation
pages. Only the three original GL papers were read completely; other entries
use the specified abstracts, definitions or algorithm sections. Secondary search
aggregators and social-media results were excluded as evidence.

## Search protocol and limitations

Query groups executed: (1) graph-logical non-basic optimization/equivalent
transformations; (2) all-terminal reliability, Boolean vertex elimination,
star-mesh and dependent edges; (3) exact network reliability, BDD frontier and
treewidth; (4) DAG-aware AIG rewriting; (5) equality saturation and extraction;
(6) dynamic connectivity and partition refinement; (7) graphset/hypergraph tools.
Search date 2026-10-12, English web index plus backward references in the original
papers and public implementation repositories. Included sources define a
transformation, representation, exact reasoning method, optimizer or semantic
boundary directly relevant to this candidate. No claim that every relevant work
was retrieved, and no claim that an exact-phrase search establishes absence.

| Primary source / year | Verified identifier / inspected scope | Known result relevant here | Difference / implication for our claims |
|---|---|---|---|
| Romankevich et al., IJEM 2026 | [10.5815/ijem.2026.03.15](https://doi.org/10.5815/ijem.2026.03.15), complete PDF §§3–6 | aligned conditional composition; zero edges, unit splitting/attachments, graph alignment | these methods and reproduction are prior coauthored research |
| Romankevich et al., HAIT 2026 | [10.15276/hait.09.2026.03](https://doi.org/10.15276/hait.09.2026.03), complete PDF | conditioned edge saturation, vertex gluing and unit contractions | wedge and local contraction are valid conventional baselines, not inventions |
| Romankevich et al., AAIT 2026 | [10.15276/aait.09.2026.25](https://doi.org/10.15276/aait.09.2026.25), complete PDF | donor surplus/orphan vectors and sliding redundancy | physical/virtual variables must remain distinct; source terminology issue retained |
| Rose, Tarjan, Lueker, 1976 | [10.1137/0205021](https://doi.org/10.1137/0205021), publisher abstract | graph vertex elimination, fill and ordering problems | elimination or min-fill alone cannot be claimed new; graph fill is not itself all-terminal Boolean equivalence |
| Wood, 1985 | [10.1002/net.3230150204](https://doi.org/10.1002/net.3230150204), publisher abstract | factoring with polygon-to-chain network reliability reduction | probability-preserving reductions under their assumptions cannot be copied as independent-edge arithmetic for correlated GL predicates |
| Bryant, 1986 | [10.1109/TC.1986.1676819](https://doi.org/10.1109/TC.1986.1676819), [author PDF](https://www.cs.cmu.edu/~bryant/pubdir/ieeetc86.pdf), definitions/representation sections | canonical reduced ordered decision diagrams; ordering and worst-case size limitations | fixed-order reference BDD is essential; finite truth-table compilation cost must be visible |
| Mishchenko, Chatterjee, Brayton, 2006 | [10.1145/1146909.1147048](https://doi.org/10.1145/1146909.1147048), [author algorithm PDF](https://people.eecs.berkeley.edu/~alanmi/publications/2006/dac06_rwr.pdf) | DAG-aware rewriting, shared logic and balancing in ABC | common-subexpression reuse or Boolean simplification is established logic synthesis |
| de Moura, Bjørner, 2008 | [Microsoft author page](https://www.microsoft.com/en-us/research/?p=825739), abstract/API context | SMT decision procedures in Z3 | solver UNSAT only supports the actual encoding/instance; preserve unknown and timeout |
| Goharshady, Mohammadi, 2017 preprint | [arXiv:1712.09692](https://arxiv.org/abs/1712.09692), author abstract | exact source-to-target reliability using small treewidth | target reachability differs from all-terminal connectivity; no direct semantic substitution |
| Inoue et al., INFOCOM 2018 | [10.1109/INFOCOM.2018.8485859](https://doi.org/10.1109/INFOCOM.2018.8485859), publisher abstract and [NTT authors' account](https://www.ntt-review.jp/archive/ntttechnical.php?contents=ntr201811fa3.html) | best-first BDD search for reliability/cost network design | optimizes network design/reliability, not an invariant operational Boolean function; search under budget is known |
| Willsey et al., POPL 2021 | [10.1145/3434304](https://doi.org/10.1145/3434304), [conference primary page](https://popl21.sigplan.org/details/POPL-2021-research-papers/23/egg-Fast-and-Extensible-Equality-Saturation), abstract/extraction discussion | equality saturation, rebuilding and cost extraction | saturation, keeping alternatives and selecting by costs are established; our beam is not egg |
| Holm, de Lichtenberg, Thorup, STOC 1998 | [10.1145/276698.276715](https://doi.org/10.1145/276698.276715), publisher/author introduction | fully dynamic connectivity under edge updates | update/query complexity is not static GL representation minimization or exhaustive state equivalence |
| Paige, Tarjan, 1987 | [10.1137/0216062](https://doi.org/10.1137/0216062), publisher abstract | relational coarsest partition/refinement | transition/relational equivalence is not automatically equality of all-terminal operational functions |
| Inoue, Iwashita, Kawahara, Minato, 2016 | [Graphillion implementation and author citation](https://github.com/graphillion/graphillion), README/technical-report description | compressed families of labeled graphs with BDD/ZDD techniques | graph-family enumeration is relevant prior art; no claim to have benchmarked Graphillion |

## Implementations and versions

Actual research environment: Z3 Python distribution **5.1.0.0**, NetworkX 3.7,
Hypothesis 6.169.0, Python 3.12.13; exact dependency freeze in requirements.txt.
Existing pure-Python ROBDD is faultgraph-lab 0.1.0 at baseline
1b2dc138e01bf39d30f4e4ac240c6c9d2f66b45e. ABC inspected repository revision:
`8b2a6fd05e7b0d922c07202d9af5e6bffe79a23d` (not executed as a comparator).
egg latest-release API returned HTTP 404; no version or successful run is invented.
Graphillion, PRISM and Storm are not executed. Mark these as missing comparisons,
not simulated winners/losers. A verified temporal translation is absent.

## Gap decision and priority boundary

Proceed with **cut placement of an all-terminal elimination obligation under
correlated Boolean edge predicates**, plus bounded search over elimination order.
Known foundations: fill, cut separation, implication, DAG sharing and Pareto/beam
search. The new work is a prospective empirical question and executable test of
this combination against declared comparators on distinct native mechanisms.
No retrieved source establishes priority for the exact combination, but the bounded
search cannot establish its novelty either. Claim status: **UNESTABLISHED**.

Principal refutation: no meaningful runtime benefit over both local reduction and
global guarding within the declared DAG bound on at least three heldout families.
The BDD or simple greedy method may outperform the candidate. Publish that outcome.
Independent humans must review source interpretation, closest work and practical
family relevance before any scientific-priority or publication claim.
