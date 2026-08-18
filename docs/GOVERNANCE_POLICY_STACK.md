# MORNS governance and policy stack

This document is the product and engineering specification for MORNS governance. It is not a substitute for final terms drafted or reviewed by counsel.

## Separate the things being governed

MORNS has four legally and operationally distinct surfaces:

1. **Software** — code people install and modify.
2. **Hosted service** — accounts, APIs, maps, Rooms, Passport, and federation operated by MORNS.
3. **Community dataset** — observations and derived aggregates contributed by independent receivers.
4. **Federation** — independently operated stations exchanging data under a shared protocol and operator agreement.

One document must not pretend to govern all four. Each surface needs its own terms, version, acceptance event, and enforcement mechanism.

## Licensing decision required

The repository uses Apache License 2.0 and is open-source software. The code license permits commercial use; restrictions on commercial exploitation apply to the official hosted service and its community observation dataset, not to copies of the software.

Recommended separation:

- Keep the station software Apache-2.0 so it remains open source.
- Protect the MORNS name and marks through a separate trademark policy.
- Govern the hosted service through Terms of Service and an Acceptable Use Policy.
- Govern access to and reuse of community observations through separate Community Data Terms.
- Require federation operators to accept a Federation Operator Agreement.

This permits community and commercial use of the software without granting a company the right to scrape, resell, enrich, or weaponize the hosted community dataset.

## Policy documents required before public launch

### 1. Privacy notice

Must disclose, by data class:

- what is collected, including radio observations not supplied directly by an account holder;
- purpose and legal basis where applicable;
- exact versus approximate location treatment;
- public visibility and federation recipients;
- subprocessors and cross-border transfers;
- retention period;
- access, correction, export, objection, and deletion methods;
- automated decisions, if any;
- security-contact and privacy-contact channels;
- material-change notice and effective date.

The notice must describe deployed behavior. It may not promise controls that do not exist.

### 2. Retention and erasure policy

The enforceable lifecycle is specified in `PRIVACY_LIFECYCLE.md`. Its proposed defaults are:

- raw observations and decoded messages: 30 days;
- non-reversible regional aggregates: 13 months;
- deletion/security audit metadata: 13 months;
- encrypted backup expiry: no more than 30 days after primary deletion.

Longer retention requires explicit operator choice, a stated purpose, and a proportionality review. Indefinite retention is not a selectable shortcut.

### 3. Acceptable Use Policy

Prohibited uses should include:

- stalking, harassment, doxxing, intimidation, or locating a person without authorization;
- building or selling movement histories or identity profiles;
- advertising, lead generation, insurance, employment, credit, housing, or eligibility decisions;
- data brokerage, resale, or commercial enrichment of MORNS observations;
- bulk scraping, enumeration, or bypassing rate limits and privacy controls;
- attempting to identify pseudonymous node operators by combining MORNS with outside datasets;
- surveillance targeted by protected class, political activity, religion, medical status, immigration status, or union activity;
- malicious interference with radio networks or intentional regulatory violations;
- publishing private-channel material, keys, credentials, or content obtained without authorization;
- training facial, identity, location-prediction, or general-purpose AI models on community data without a separately approved agreement;
- representing MORNS as emergency, life-safety, dispatch, or guaranteed-delivery infrastructure.

Good-faith security research requires coordinated disclosure and must minimize collection of unrelated data.

### 4. Community Data Terms

The initial hosted dataset should be available for personal, educational, amateur-radio, emergency-preparedness, civic, and non-commercial research uses subject to privacy controls, attribution, rate limits, and purpose limitation.

The following require a separately negotiated data agreement, if allowed at all:

- commercial redistribution or resale;
- advertising or commercial analytics;
- data brokerage or identity enrichment;
- high-volume historical export;
- model training;
- integration into products that make decisions about individuals;
- law-enforcement bulk access.

The terms must clarify that a station contributes only data it is authorized to share, retains no ownership claim over third-party message authorship, and grants MORNS only the limited rights needed to receive, process, display, protect, aggregate, and delete the contribution.

The final dataset license needs specialist review. Software-license language must not be copied onto radio observations or message content.

### 5. Federation Operator Agreement

Every public peer must:

- publish an operator identity and security/privacy contact;
- use supported software and authenticated federation credentials;
- preserve provenance and never relabel imported or simulated data as physical RF reception;
- honor precision, retention, consent, and publication metadata;
- process signed deletion tombstones before serving restored or delayed data;
- report breaches and compromised keys promptly;
- prohibit unauthorized private-channel collection;
- prevent public indexing until Setup and policy checks pass;
- provide an accurate clock and auditable software/configuration version;
- accept suspension or revocation for abuse, stale software, falsified observations, or ignored deletion requests.

Federation must fail closed: a peer that cannot prove policy compatibility receives no restricted data.

### 6. Law-enforcement and government request policy

MORNS should:

- require valid, correctly scoped legal process;
- reject informal bulk-location requests;
- provide only data actually retained and responsive to the request;
- challenge overbroad requests where lawful and practical;
- notify affected users before disclosure unless legally prohibited;
- publish aggregate transparency reports;
- never build a surveillance capability solely to satisfy a hypothetical future request;
- document emergency disclosure criteria and require retrospective review.

### 7. Security and vulnerability policy

Must include supported versions, private reporting, response targets, safe-harbor language for good-faith research, coordinated disclosure, key rotation, breach notification, dependency response, and federation credential revocation.

### 8. Community and moderation policy

Must cover public names, messages, Rooms, abuse reports, appeals, moderator access, evidence retention, conflicts of interest, sanctions, repeat abuse, and transparency. Moderation logs must not become a shadow indefinite archive of deleted content.

### 9. Trademark policy

Independent deployments may truthfully say they run MORNS software. They may not imply that an altered, non-compliant, or unaffiliated service is the official MORNS network. A compatibility mark can require passing published conformance tests.

### 10. Research policy

Research access should use purpose-bound credentials, minimum necessary fields, expiring exports, disclosure review, publication safeguards, and deletion commitments. Human-subject or re-identification research requires appropriate ethics review. “Research” is not a blanket exception to privacy or non-commercial restrictions.

## Consent and versioning

- Every policy has a semantic version, effective date, and public change log.
- Material changes require notice and renewed acceptance where appropriate.
- Consent is granular: operating a station, publishing its location, federating observations, retaining message text, joining a Room, and enabling Passport are separate choices.
- Declining optional processing must not disable unrelated local functionality.
- Withdrawal must be as easy as enrollment and must trigger the documented deletion workflow.

## Enforcement architecture

Policies become real through controls:

- scoped credentials and least privilege;
- rate limits and export quotas;
- auditable provenance;
- retention jobs with deletion receipts;
- federation tombstones and acknowledgement tracking;
- precision reduction before publication;
- abuse detection and operator suspension;
- immutable policy-version acceptance records that contain no unnecessary content;
- recurring tests that prove deleted or private records cannot reappear.

## Public-launch release gate

Do not enable public accounts, public federation, Passport, Rooms, or bulk exports until:

1. final policies have owner and legal review;
2. product behavior matches every material promise;
3. deletion, export, appeal, and abuse-report flows are usable without staff intervention;
4. backups and federation peers pass erasure tests;
5. policy versions and consent receipts are recorded;
6. a privacy-impact and threat-model review is complete;
7. an incident-response owner and public contact exist.
