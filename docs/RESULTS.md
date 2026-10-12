# Results and claim boundaries

The following records were exported unchanged from the original research archive.
They are historical results, not new full-study runs performed while creating
this edition. This edition provides the implementation, fresh-run commands,
selected original inputs and summaries; full historical worker logs remain in
the private provenance archive.

| Study | Reported scope | Primary outcome |
| --- | --- | --- |
| Paper reproduction | Eight processors, all 256 assignments; 59 operational states and 22 specified exceptional states | Published example reproduced; finite transcription/oracle agreement |
| Native guard v2 | 120 cases, six synthetic native families, eight arms, 1,305,600 arm-state checks | Optimization hypothesis refuted; no correctness mismatches |
| Symbolic v3 | 90 cases, six provider topologies, eight arms; 680 exact certificates of 720 runs | Inconclusive primary outcome; fixed-order limits/timeouts retained |
| Native chain v4 | 90 cases, six provider/core clusters, six arms; 540 exact certificates | Supported on the frozen scope: six qualifying clusters |

The v4 comparison uses established degree-two reduction ideas with an explicit
Boolean obligation for all required internal vertices. An exact certificate
covers its concrete finite Boolean instance. A solver timeout is unresolved,
and a sampled truth check is not a universal equivalence proof. Six clusters
are six clusters, not 90 independent real-world systems.

Original exported records:

- [v2 hypothesis](../artifacts/flagship/native-guard-v2/hypotheses.json)
- [v3 hypothesis](../artifacts/flagship/native-symbolic-v3/hypothesis.json)
- [v4 hypothesis](../artifacts/flagship/native-chain-v4/hypothesis.json)
- [v4 family results](../artifacts/flagship/native-chain-v4/family_results.csv)
- [v4 Linux comparison](../artifacts/flagship/v4-ci/replication-comparison.json)

Known limits: static all-terminal connectivity; user-specified component laws;
limited historic topology subsystems; no validation of actual deployed failure
policies; no claim of new mathematical priority, universal correctness of arbitrary
inputs, global optimality, or independent human scientific review.
