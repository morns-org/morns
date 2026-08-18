# Hosted MORNS Members and Base Stations

This document defines the planned hosted-service boundary. The current repository remains a local single-base-station MVP and must not present these features as operational until authentication, authorization, abuse controls, and deletion are implemented and tested.

## Member area

A member account can own one or more base-station registrations and one or more Passport device claims. Account identity is stored separately from public radio observations. Public profiles and Passport publishing are opt-in.

## Base-station registration

Registration creates:

- an immutable internal station identifier;
- an operator-controlled public name and description;
- a precise, approximate, or private location policy;
- public-map participation and statistics-sharing choices;
- a revocable API credential shown only once;
- credential metadata: prefix, hash, scopes, creation, last use, expiry, and revocation;
- station software, protocol, and health metadata;
- an auditable ownership-transfer and deletion lifecycle.

API credentials are random bearer secrets stored only as slow or keyed hashes. They are scoped per station (`observations:write`, `station:health`, and optional future scopes), rate-limited, independently revocable, and never reused as a member login credential. Key rotation overlaps briefly so a station can rotate without losing data.

The public map shows only stations that explicitly enable publication. Location precision, health, uptime, observation totals, messages, farthest contact, and historical charts are individually publishable. Private station details never appear in public API responses.

## Passport

Passport is member-controlled personal history, not base-station configuration. A member proves control of a device, chooses a retention period, and sees which participating base stations observed it. The member can:

- keep the entire Passport private or publish a selected profile;
- show coarse geography without exposing exact receiver coordinates;
- publish aggregate counts without publishing a trail;
- hide an individual station or sighting;
- revoke a device claim;
- export or erase Passport data.

Base-station operators cannot browse private Passports. Other members cannot claim a device merely by knowing its node ID. Public Passport output must be generated from a separate disclosure view so private fields cannot leak through ordinary serialization.

## Minimum security gate before implementation is enabled

- verified member authentication and recovery;
- CSRF-resistant browser sessions and secure cookies;
- authorization tests for every account, station, key, device, and Passport object;
- hashed, scoped, rotatable station API credentials;
- device-control proof resistant to passive node-ID harvesting;
- rate limits, abuse reporting, and administrative audit logs;
- retention, export, deletion, and right-to-be-forgotten jobs;
- location-precision and hidden-station non-disclosure tests;
- separation between decoded message retention and non-content observation statistics.
