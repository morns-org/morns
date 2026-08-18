# MORNS release gates

A release is not deployable merely because its dashboard starts. Every public release must record evidence for each applicable gate.

## Automated gates

- Unit, API, schema, authentication, and provenance tests pass.
- Normal startup creates no simulated observations.
- Simulator startup is explicit and visibly disclosed.
- Docker image builds on ARM64 and AMD64.
- A clean database survives restart and upgrade.
- USB disconnects do not corrupt the event log.

## Platform gates

- Raspberry Pi OS installation completes from the public repository.
- The current physical RAK4631 fixture produces a `LORA` observation through direct Linux serial ingestion.
- The macOS native collector delivers an observation from the current physical RAK4631 fixture to the Docker server.
- The compatibility matrix includes physical fixtures from at least two manufacturers before MORNS claims general hardware support.
- No runtime behavior depends on a manufacturer allowlist; differences are capability- or transport-driven.
- Unknown models that satisfy the Meshtastic transport and packet contract may enroll without a code change.
- Collector authentication rejects missing and incorrect credentials.
- Simulator, MQTT, import, and physical LoRa provenance remain distinguishable.

## Release evidence

The release notes must identify the tested commit, hardware, operating systems, test results, known limitations, and any gate explicitly deferred. A release with a deferred hardware gate must be labeled pre-release and must not claim hardware support for that platform.
