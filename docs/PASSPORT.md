# MORNS Passport

Passport is a planned user feature, separate from receiver setup.

It gives a MORNS user a private, portable view of their registered Meshtastic devices and the places those devices have been observed while traveling between participating MORNS regions.

The intended scope includes:

- user-owned device registration and proof of control;
- a personal map spanning multiple MORNS receiver networks;
- device aliases, ownership state, and travel history;
- per-device sharing, retention, precision, and deletion controls;
- an explicit distinction between private Passport history and public observation data;
- opt-in federation across MORNS installations.
- private-by-default statistics for the number of participating base stations that observed each registered device;
- selectable geographic summaries and time ranges;
- per-sighting and per-base-station visibility controls, including the ability to hide an individual base station without deleting the underlying station;
- separate controls for publishing a profile, a device, aggregate statistics, geography, and individual sightings.

## Ownership and tagging

A user must prove control of a Meshtastic device before MORNS associates observations with their Passport. A node name or numeric ID alone is not proof of ownership. Passport matching uses a privacy-preserving device claim or challenge, and the hosted service must not disclose which private Passport owns a radio identity.

“Tagged across” means observed by a participating base station inside the user-selected retention period. It is not a claim that the person was physically present, and it does not permit MORNS to triangulate or infer an exact location from signal reports.

Passport defaults to private. Publishing a Passport requires an explicit, reversible choice. Hidden base stations and sightings are excluded from public maps and public totals, while the owner may choose whether they remain visible privately. Erasure and retention controls apply independently to the account, claimed devices, and sighting history.

Passport is not the station configuration screen, is not required to operate a receiver, and must not silently expose a person's travel history. Account, cryptographic identity, consent, abuse prevention, and location privacy need a dedicated product and security review before implementation.
