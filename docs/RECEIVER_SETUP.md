# MORNS Base Station Configuration

Base Station Configuration enrolls a stationary or semi-stationary MORNS observation station. It is manufacturer-agnostic: runtime behavior is selected from discovered capabilities and Meshtastic protocol support, never from a vendor allowlist. “Setup” is not a product name, and Passport is reserved for personal travel and device history.

## Identity and capabilities

- Stable MORNS receiver ID
- Meshtastic node ID
- Manufacturer, model, hardware ID, and firmware version (informational)
- Connection transports: serial, TCP, BLE, or MQTT
- Radio region, modem preset, frequency slot, and device role
- GNSS, telemetry, power, network, display, and storage capabilities
- Fixed, semi-fixed, or mobile operation

## Operator choices

- Receiver display name and region
- Precise, approximate, or private location publication
- Receiver coordinates and public coordinate precision
- Display-only observation-zone radius
- Message logging, retention, federation, and export choices

## Setup rules

1. Discover hardware and protocol capabilities without changing settings.
2. Identify the local Meshtastic node so self-telemetry is classified `LOCAL`.
3. Ask the operator for choices that cannot be discovered.
4. Show the complete proposed setup and any device-setting diff.
5. Require confirmation before writing radio settings or publishing receiver information.
6. Retain revision history for material configuration changes.

Device configuration and MORNS publication are separate transactions. An operator may configure either without enabling the other. When a MORNS location policy is also applied to a Meshtastic device, the UI must disclose that it changes what the radio transmits, show the exact before/after values, and obtain confirmation for every affected device.

## Station groups

A base station may contain multiple physical receivers, and multiple base stations may form one logical observatory. MORNS preserves both levels:

- the logical station or group used for combined dashboards and counts;
- the physical receiver that actually heard each packet and measured RSSI/SNR;
- the ingress transport used to deliver that observation to MORNS;
- every independent reception of the same RF packet.

Combined views may deduplicate logical packets, but raw receiver observations are never collapsed or reassigned. Station grouping must not weaken a member's location, retention, or publication policy.

Incomplete setup is an explicit state. Coverage and public federation must not activate until the required identity, provenance, and location-policy fields are complete.

## Operational statistics

The local base-station dashboard reports measured, time-bounded statistics:

- process uptime, clearly distinguished from hardware or lifetime uptime;
- health state and the evidence used to calculate it;
- observations, distinct nodes, and decoded messages;
- peak observations, nodes, and messages in disclosed aggregation buckets;
- last observation time;
- farthest positioned contact only when a node intentionally broadcast a position.

MORNS must never infer or publish a farthest-contact distance from RSSI alone. Every maximum must identify both the selected history window and the aggregation bucket.

## Compatibility contract

RAKwireless, Heltec, Seeed Studio, LilyGO, and other Meshtastic devices use the same normalized observation model. Vendor-specific code is permitted only behind a capability or transport adapter when protocol behavior genuinely differs.

A receiver qualifies by satisfying the protocol contract:

- exposes a supported Meshtastic client transport;
- provides a stable local node identity;
- delivers decoded packet metadata through the Meshtastic client API;
- reports capabilities it actually supports instead of inheriting assumptions from a model name.

Unknown hardware may enroll when it satisfies the contract. Unsupported capabilities are shown as unavailable rather than making the entire receiver unsupported.

Compatibility evidence is recorded as `protocol-compatible`, `automated-verified`, or `physical-verified`. A physical RAK fixture establishes evidence for that fixture only; it does not imply that MORNS requires RAK.
