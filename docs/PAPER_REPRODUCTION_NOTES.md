# Source reproduction notes

All three cited publisher PDFs were retrieved and read completely, including
references and declarations. Relevant IJEM pp.260–264 and AAIT pp.368,372–373 were
also visually inspected. The source manifest contains exact SHA256 checksums.
No original author source code or private datasets were received.

## IJEM (June 8, 2026)

Vitaliy Romankevich, Kostiantyn Morozov, Alexei Romankevich, Petro Malezhyk,
Lefteris Zacharioudakis, *A Generalized Method for Constructing Graph-Logical
Models of Non-Basic Fault-Tolerant Multiprocessor Systems via Model Combination*,
16(3):254–269, DOI [10.5815/ijem.2026.03.15](https://doi.org/10.5815/ijem.2026.03.15).
The PDF states CC BY 4.0. Eq (2), Propositions 2–6 and the modeling method are
reproduced prior research, not attributed to this software as inventions.

Pages 259–260 provide the 22 vectors and B1/B2 partition. They are transcribed
literally in `paper.py` and `artifacts/reproduction/paper8/inputs.json`. Original
digit order is retained. Independent oracle: at most two failures OR exact membership
in the listed 22 states. It reads no GL edges or expression results. All 256 states
are stored, including all failures and zero-match witnesses if present.

Figure 3 provides K1′ (7 vertices, 9 edges) and K2′ (8 vertices, 10 edges).
Figure 4 gives the first alignment: split K1 alpha, keep f1/f8 on alpha, move f7
to theta, attach a unit edge, add the indicated zero chords and remap consistent
edge IDs. Eq (2) composition is constructed separately from the printed simplified
K12 functions and exhaustively checked against them. Figure 5's 11-edge K12′
variant is transcribed literally and independently checked against the system oracle.

Figure 8a M uses the exact gamma/theta root merge (alpha3/beta8 in HAIT notation).
Figure 8b M′ uses the source unit contractions, fused f6/f8 formula and beta/eta
root merge. An additional mechanically composed M arm uses a different permitted
root choice; it is explicitly labeled unsimplified and its metrics are not substituted
for the printed M. The first development run used this alternate merge for M;
it passed truth tests, but was refined to the literal Fig.8 topology for fidelity.

| Model | V | E | OR | AND | NOT | Total |
|---|---:|---:|---:|---:|---:|---:|
| K12 | 8 | 12 | 21 | 35 | 9 | 65 |
| K12′ | 8 | 11 | 23 | 37 | 13 | 73 |
| M | 14 | 19 | 33 | 29 | 14 | 76 |
| M′ | 12 | 16 | 32 | 29 | 12 | 73 |

Published Table 1 is stored separately from measured values. All above values
match the literal formula tree operation convention arity-1 for AND/OR and one
operation per NOT occurrence. The smaller K12′ graph has more logic operations
than K12: a real tradeoff, not universally superior compactness.

Independent second-person transcription review and original-author code comparison
remain pending. A matching table is computational evidence, not author certification.

## HAIT (February 18, 2026)

Romankevich, Morozov, Romankevich, Halytsky, Zacharioudakis,
[10.15276/hait.09.2026.03](https://doi.org/10.15276/hait.09.2026.03), 9(1):30–45,
CC BY 4.0. Publisher `op.edu.ua` retrieval failed; the publisher `od.ua` mirror
provided the full PDF. Eq (1) modifies f to f OR NOT selector and merges one
vertex from each graph. Underlying graphs must be connected. That assumption is
enforced explicitly; otherwise an inactive auxiliary can remain disconnected.
The paper's Example 1 agrees with the IJEM source system and M/M′ constructions.
Example 2's nine-processor source is reviewed but not separately reproduced here.

## AAIT (June 18, 2026)

Same five HAIT coauthors, [10.15276/aait.09.2026.25](https://doi.org/10.15276/aait.09.2026.25),
9(3):366–383, CC BY 4.0. Literal donor functions for Examples 1/3 are checked over
all 256/32 states. Arithmetic ground truth counts surplus processors when donor
working, surviving orphan processors when failed. Resource-vector bits represent
virtual availability counts, not physical processor IDs.

Examples 1/2 recipient formulas are transcribed from pp.373–374 into the extended
11-/10-bit models. Their entire virtual input domains independently match a
four-survivor threshold. Composed with the donor outputs, both 14-physical-processor
examples match the separate resource-arithmetic oracle over 16,384 states each.
The four-resource cap is checked on every five-bit virtual state.

**Source issue requiring author review:** p.368 calls K(m,n) an (m+1)-out-of-n:G
system, although its own preceding definition allows at most m failed processors.
For n=8,m=3 these imply four versus five survivors; `11110000` distinguishes them.
The literal donor graph requires five survivors, agreeing with its failure-tolerance
definition and the IJEM convention. We preserve this discrepancy and do not invent
an author-approved correction or general MLE constructor. The printed revision year
2926 on p.381 is also retained as a publication metadata typo.

The full 27-processor sliding system in Example 3, AAIT Table 1 complexity and
generic dual-MLE generation are not claimed reproduced. They require a separate
source-reviewed implementation and scoped exact/symbolic validation.

