# MORNs Receiver Setup

Receiver Setup enrolls a stationary or semi-stationary MORNs observation station. It is manufacturer-agnostic: runtime behavior is selected from discovered capabilities and Meshtastic protocol support, never from a vendor allowlist.

## Identity and capabilities

- Stable MORNs receiver ID
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

Incomplete setup is an explicit state. Coverage and public federation must not activate until the required identity, provenance, and location-policy fields are complete.

## Compatibility contract

RAKwireless, Heltec, Seeed Studio, LilyGO, and other Meshtastic devices use the same normalized observation model. Vendor-specific code is permitted only behind a capability or transport adapter when protocol behavior genuinely differs.

A receiver qualifies by satisfying the protocol contract:

- exposes a supported Meshtastic client transport;
- provides a stable local node identity;
- delivers decoded packet metadata through the Meshtastic client API;
- reports capabilities it actually supports instead of inheriting assumptions from a model name.

Unknown hardware may enroll when it satisfies the contract. Unsupported capabilities are shown as unavailable rather than making the entire receiver unsupported.

Compatibility evidence is recorded as `protocol-compatible`, `automated-verified`, or `physical-verified`. A physical RAK fixture establishes evidence for that fixture only; it does not imply that MORNs requires RAK.
