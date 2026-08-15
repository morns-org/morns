# Security

Please report vulnerabilities privately through GitHub Security Advisories rather than opening a public issue.

MORNs only records message content that the attached Meshtastic device delivers to its client API. Operators are responsible for channel membership, notice, consent, retention, and publication policies in their jurisdiction. Do not configure unattended public receivers with private channel keys.

Remote collector ingestion is disabled unless `MORNS_INGEST_TOKEN` is configured. Use a unique random token, keep the default Docker binding on localhost, and never commit `.env`. The endpoint assigns `LORA` provenance to authenticated collector submissions and rejects submissions labeled as simulator data. Possession of the bearer token is the MVP trust boundary; a compromised authorized collector could still fabricate an observation. Simulator events use a separate in-process path.
