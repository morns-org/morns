# Contextual map-layer architecture

MORNS means **Mapping Observed Radio Network Signals**. It is protocol-agnostic. Meshtastic is its first radio adapter, not its product identity.

## Separation of evidence

The map must distinguish three evidence classes:

1. **MORNS observations** — packets or events directly observed by a registered receiver.
2. **Node-declared data** — positions and metadata asserted by a transmitting device.
3. **Context layers** — records obtained from an identified external authority.

Context layers never count as nodes, receivers, contacts or coverage. Their markers and popups must visibly name the provider and retrieval time.

## Initial source candidates

### United States

- National Weather Service observation stations and active alerts
- NOAA Weather Radio transmitter sites
- USGS stream gauges and water observations
- EPA/AirNow air-quality monitoring sites

### Canada

- Environment and Climate Change Canada weather and alert feeds
- Water Survey of Canada hydrometric stations

Community-maintained repeater, APRS, gateway or mesh-site datasets require a terms and redistribution review before integration. A publicly viewable map is not automatically an open data license.

## Adapter contract

Each layer adapter supplies:

- stable provider and feature identifiers;
- coordinates and declared precision;
- feature type and public display name;
- observed/effective time and retrieval time;
- upstream URL and license/terms URL;
- freshness policy and last successful refresh;
- country/region coverage;
- normalized health state: current, delayed, stale or unavailable.

Adapters cache only what their source terms permit. A source outage leaves the MORNS receiver map operational and marks the affected layer stale or unavailable.

## User experience

- A Layers control is reachable directly from every map.
- Layers are grouped as Mesh, Weather, Environment, Water and Emergency.
- High-value local layers may be suggested but are not silently enabled.
- The legend changes with enabled layers.
- Layer selections persist per user/browser.
- Time-aware layers follow their own valid time windows rather than inheriting an incompatible RF-observation window.
- Public and private station-location policies continue to apply independently of contextual data.
