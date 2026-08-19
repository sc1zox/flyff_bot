# World reference data

`monster_ids.json` maps the monster identifiers written into the client's `.rgn` region
scripts to the detector class names in `models/labels.txt`, so an extracted spawn zone can be
addressed by the same name the operator selects in the dashboard (US-045).

The client's own identifier-to-name table (`propMover.txt`) ships only inside the obfuscated
`data.one` archive, which this project does not read. The shipped mapping therefore pairs the
six Eden identifiers with the six Eden labels in ascending identifier order. It is an
assumption, not an extraction: correct an entry here if a zone turns out to spawn a different
monster than its name claims. An identifier that is absent from this file still extracts, and
its zones keep their numeric identifier and carry no name.
