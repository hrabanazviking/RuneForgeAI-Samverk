# Grayscale coherence (S-383)

The whole UI audited in grayscale: `samverk/grayscale_coherence.py`
registers every colour-bearing UI signal in `MEANING_CARRIERS` with
the text and icon channels that carry the same meaning, and
`audit_grayscale` proves no meaning is lost when colour is removed:
no carrier may be colour-only, and two carriers in one group whose
grayscale values collapse together must already be separated by
text or icon.

## Proof

The proof is the rendered grayscale table from
`render_proof_report()` — every carrier with its colour, its
grayscale value, and its surviving channels — regenerated from the
standing registry, so the proof can never drift from the code it
proves. The battery re-runs the audit on every build; a planted
colour-only carrier and a planted unseparated collapse are both
named by the audit in tests.
