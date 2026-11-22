# Target sizes (S-386)

Interactive targets are at least 44x44px and controls stand in the
40-48px band: `samverk/target_sizes.py` holds the standing target
registry and two audits — `audit_targets` over the registry, and
`audit_rendered_nav` over S-382's rendered primary navigation, so
every link a rendered page actually emits must resolve to a
registered, passing target. The first audit run caught the settings
Save control standing at 40px tall — inside the control band but
under the 44px target law; it now stands at 44px, where the two
laws overlap.
