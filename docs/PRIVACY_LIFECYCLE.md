# Privacy, retention, and erasure lifecycle

MORNS must make the lifecycle of every stored data class visible and enforceable. A privacy notice alone is not sufficient.

## Data classes and proposed defaults

| Data class | Proposed public-service default | User control |
| --- | --- | --- |
| Account and authentication records | While the account is active; erase after account closure | Export and delete account |
| Receiver registration and exact location | While registered | Change precision, unpublish, or delete receiver |
| Raw RF observations | 30 days | Station operator may shorten or disable federation |
| Decoded public-channel messages | 30 days | Station operator may shorten; verified author may request erasure |
| Approximate coverage aggregates | 13 months | Must not preserve message text, precise movement, or reversible identifiers |
| Security and deletion audit records | 13 months | Minimal event metadata only; never retain deleted content |
| Encrypted backups | Maximum 30 days after primary deletion | Expire automatically; never restored without replaying deletion tombstones |

These are proposed defaults, not silent constants. Setup must disclose them before public federation is enabled. A station can choose shorter periods. Longer retention requires an explicit choice and a plain-language explanation.

Self-hosted operators control their own local database, but MORNS must provide the same retention and deletion tools locally. Federation does not grant the public service indefinite rights to a station's data.

## Data minimization

- Store the least precise receiver location needed for the selected publication policy.
- A postal code is an input to an approximate-area lookup, not permanent profile data. Discard it after deriving the selected area unless the user explicitly asks MORNS to retain it.
- Browser geolocation requires an explicit user gesture and browser permission. Store the reported accuracy with the chosen point.
- Do not infer a location from an IP address.
- Separate public radio observations from account, billing, and authentication identity.
- Do not retain raw payloads merely because an aggregate was calculated from them.

## Right to erasure

MORNS must provide an authenticated, understandable deletion flow for:

1. an account;
2. a registered receiver and its exact or approximate location;
3. a Passport device and its private travel history;
4. MORNS Room membership, keys, and server-held ciphertext;
5. observations or messages associated with a node whose ownership can be proven.

Deleting an account must not require deleting legitimately independent public infrastructure records owned by somebody else. Conversely, deleting a receiver must remove the link between that receiver and its owner even if non-identifying regional aggregates remain.

### Proving node control

A request concerning an unauthenticated RF identity cannot rely on a typed node ID alone. MORNS should issue a nonce and accept a signature from the node's registered public key or another reviewed Meshtastic-compatible proof. Recovery and legacy-device paths require abuse review because an attacker could otherwise erase another person's history.

## Federated deletion

Deletion is a protocol event, not a best-effort support ticket.

- The authoritative service creates a signed deletion tombstone with scope, subject, request time, and expiry.
- Every federation peer acknowledges receipt and records completion without copying the deleted content into its audit trail.
- Offline peers process tombstones before accepting or serving older replicated data.
- Aggregates are rebuilt or suppressed when they could identify the erased subject.
- The requester can see `requested`, `propagating`, `completed`, or `partially completed`, including any independently operated peer that has not acknowledged deletion.
- Tombstones outlive the longest backup window so restored backups cannot resurrect erased data.

## Safety and abuse boundaries

- Erasure endpoints require authentication, CSRF protection, rate limits, and recent re-authentication.
- No unauthenticated HTTP endpoint may wipe a station database.
- Legal preservation requests, security incidents, and disputes must be narrowly scoped, time bounded, and disclosed where legally permitted.
- Public radio transmission does not by itself establish consent to indefinite aggregation, precise movement history, or identity enrichment.

## MVP release gate

The current single-station MVP has no public accounts or federation. Before either is enabled, release acceptance must include:

- per-class retention settings and scheduled enforcement;
- export and deletion interfaces;
- authenticated receiver deletion;
- deletion-tombstone propagation and retry tests;
- backup-expiry and restore tests;
- proof that erased records do not reappear in maps, search, caches, exports, or aggregates;
- a public privacy notice that matches the implementation.

Until those controls exist, MORNS must remain bound to a trusted local network and must not present itself as a privacy-complete public service.

This engineering contract is not legal advice. Before a public U.S./Canada launch, counsel must review the deployed data flows and applicable federal, provincial, state, and local requirements. Useful primary guidance includes the Office of the Privacy Commissioner of Canada's Principle 5 guidance and the California Privacy Protection Agency's consumer-rights guidance.
