# Text scaling (S-384)

125% and 200% scaling passes on every core flow:
`samverk/text_scaling.py` models each core flow's controls with
their S-381 token sizes (body 16px, small 14px) and container
widths, and re-runs the layout arithmetic at both scales. A fixed
control whose scaled text need exceeds its container is `clipped`;
fixed controls whose scaled widths together exceed their shared
row `overlap`. The standing registry passes both scales.

Designed growth, not clipping: the primary navigation is a
wrapping flex row, long button labels wrap and grow the button
taller, and titles/hints are fluid text — all marked `wraps` in
the registry. The audit's first run caught five fixed boxes that
would have clipped at 200%; the registry now records the wrapping
design those surfaces actually use.
