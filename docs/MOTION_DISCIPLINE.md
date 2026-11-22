# Motion discipline (S-391)

UI motion stays within the Lawbook's bands: micro motion
(hover, focus, toggles) at 80-140ms, transitions at 160-220ms,
ceremonial motion rationed to at most one per surface and a tenth
of all registered motion. `samverk/motion_discipline.py` holds the
registry and the audit; `reduced_motion` applies
`prefers-reduced-motion` fully — every duration becomes zero and
ceremonial motion is removed outright, because respected fully
means nothing moves, not that things move less. The registry's
first audit run caught its own ceremony at 1 of 9 motions (over
the tenth-share ration); a standing tab-switch micro motion was
registered to bring the share to exactly the ration.
