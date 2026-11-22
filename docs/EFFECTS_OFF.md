# Effects-off coherence (S-385)

Glow and texture disabled, the UI remains fully legible and
hierarchical: `samverk/effects_off.py` registers every styled
element with the channels carrying its rank, split into structural
channels (heading size on the S-381 ladder, weight, S-381 frame
strength) that survive effects-off, and effect channels (glow,
texture, shadow) that vanish. `audit_effects_off` names any pair
whose rank order is carried only by an effect, and any text whose
foreground/background contrast falls below 4.5 once a glow halo
stops propping it up. The standing registry passes both judgements.
