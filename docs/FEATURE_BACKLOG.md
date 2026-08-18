# MORNS feature backlog

This backlog records product candidates, not shipped capabilities. Every release must continue to distinguish real observations from simulated or illustrative data.

## Page-specific dashboard tiles

Each page must retain an essential, non-removable purpose while allowing secondary tiles to be configured.

### Live dashboard

- Discovery and mobile-node alerts
- Collector warnings
- Activity sparkline
- Strongest currently active nodes

### Receivers

- Receiver activity timeline and receiver comparison
- Receiver map and observation overlap
- Radio preset, frequency slot, collector and firmware versions
- Collector heartbeat, ingest latency, errors and rejected packets
- RSSI/SNR summaries, farthest contact and transport mix

### Nodes

- Recently discovered and recently active nodes
- Hardware, firmware and role distributions
- Potential mobile/static classifications and transition history
- Battery/external-power status and telemetry availability
- Position history, strongest/farthest/frequently observed nodes
- Identity changes, public-key availability and multi-receiver sightings

### Messages

- Message activity timeline, active channels and active participants
- Direct/broadcast split and receiver attribution
- Decode success, encrypted-undecodable counts and rebroadcast suppression
- Search, filters, retention status and irreversible redaction counts
- Private MORNS Rooms as a separate surface from public Meshtastic traffic

### Coverage

- Empirical heatmap and coverage over time
- Receiver-specific and overlapping coverage
- RSSI/SNR, preset and frequency-slot geographic layers
- Coverage gains/losses, distance and bearing distributions
- Mobile-node trails, data-density confidence and unpositioned counts

## Contextual map layers

Add independently toggleable, provenance-labeled layers without representing third-party sites as MORNS observations:

- official weather observation stations;
- weather-radio transmitters and alert areas;
- stream gauges and flood observations;
- air-quality monitors;
- active weather alerts and reviewed emergency layers;
- amateur-radio infrastructure only from a source whose reuse terms permit it;
- other community mesh technologies through explicit protocol adapters.

Every layer must expose its provider, retrieval time, source-data vintage, refresh status, license/terms link, geographic coverage and whether data is live, delayed or static. Third-party layers must fail independently and never fabricate cached freshness.

## Device fleet and station topology

### Full Meshtastic device administration

- Discover and enroll multiple devices through USB serial, Bluetooth, Wi-Fi/TCP, or MQTT where supported.
- Present every supported Meshtastic setting by capability group: identity, radio, channels, position, telemetry, power, network, Bluetooth, display, store-and-forward, detection sensor, canned messages, and device role.
- Read before writing, show a human-readable configuration diff, require confirmation, and retain a redacted revision history.
- Back up and restore device configuration without exporting channel keys or other secrets unless the operator explicitly requests an encrypted secret export.
- Support reusable configuration profiles with capability checks rather than manufacturer allowlists.
- Show firmware/hardware compatibility, pending restart requirements, validation errors, and the result of reading the device back after a write.
- Never change radio region, frequency, channel keys, transmit power, device role, or position behavior merely because a device was connected.

### Multiple devices at one base station

- Maintain a device inventory with stable MORNS receiver IDs, friendly names, connection path, purpose, health, and last contact.
- Allow distinct roles such as observer, local client, relay, second-band observer, test fixture, or offline spare.
- Keep each receiver's provenance on every observation even when the UI presents a combined station view.
- Detect duplicate packets heard by multiple local receivers and preserve each reception measurement while counting the logical packet once where appropriate.

### Base-station groups

- Join two or more MORNS installations into an operator-defined station group and optionally present them as one logical observatory.
- Use authenticated station-to-station enrollment with revocable credentials and no assumption that stations share a LAN.
- Deduplicate by packet identity and time window while preserving per-receiver RSSI, SNR, ingress path, timestamps, and location policy.
- Provide combined and per-station health, coverage, retention, clock-skew, overlap, and failure views.
- Define whether data stays local, replicates only inside the group, or may federate to the public MORNS service.
- Avoid a required leader: a disconnected member continues collecting locally and reconciles later according to retention policy.

### Location-privacy synchronization

- Offer an explicit `MORNS only` or `MORNS and radio` privacy scope.
- `Precise` may leave device position behavior unchanged or apply an operator-reviewed fixed position.
- `Approximate` may apply a separately reviewed coarse/fixed radio position; MORNS must explain that radio recipients can still observe whatever the device broadcasts.
- `Private` may disable Meshtastic position broadcasts or remove a fixed position, subject to device capability and an explicit warning about lost mesh functionality.
- Never claim that obscuring the MORNS map retroactively hides positions already broadcast over radio or retained by other nodes.
- Show the exact device-setting diff, require confirmation per device, verify the post-write state, and provide rollback from the pre-change backup.
- Channel-level position precision and device-level position behavior must be explained separately; the safer effective result wins when policies conflict.

## Additional administration settings

- Storage location, database size, backup/restore, export, retention execution history, and secure deletion status.
- Software and firmware update channels, update checks, maintenance windows, and rollback status.
- Health alerts for collector loss, stale receivers, disk pressure, clock drift, failed map providers, and repeated ingest rejection.
- Notification destinations including local UI, email, webhook, and optional hosted MORNS account.
- Network binding, trusted proxies, TLS, outbound-provider allowlists, offline mode, and map tile/cache controls.
- Local users, roles, session lifetime, recovery codes, audit log, OIDC providers, and API/service credentials.
- Units, locale, server time zone, clock source, accessibility, map defaults, and dashboard defaults.
- Public federation, station-group replication, Passport participation, message publication, and per-data-class consent.
- Data export, deletion, right-to-be-forgotten requests, blocked node IDs, and privacy incident controls.

## Product constraint

Configuration may change presentation, but it must not remove the core utility of a page: Nodes retains its registry, Messages its history, Coverage its geographic evidence, and Receivers its base-station health.
