# Provenance

> English translation for reference; the Chinese original prevails.

The public release of 栗栗 (Tamias) is derived from the author's complete evidence
copy — a desensitized derivative of the same codebase. At release time only the
development environment's private information (local absolute paths, usernames,
key placeholders, etc.) was removed; the functional code is identical to the
evidence copy.

## Evidence Hash Anchoring

Before publishing this repository, the author generated a git bundle of the
complete evidence copy, and recorded its SHA-256 hash with a trusted timestamp:

- Evidence bundle SHA-256:
  `46211014029a214eae7d13fb7da76f694db06645c0697658c504d06c4a37d639`
- Evidence bundle size: 164,134,201 bytes (~156 MB)
- Timestamp attestation: 2026-09-13 21:28:39 (tsa.cn desensitized attestation —
  only the hash is locked, file contents are never uploaded)

## How to Verify Provenance

The author retains the complete evidence-copy bundle. To prove that "the author
already held the complete manuscript when the public version was published,"
one can compute the SHA-256 of the evidence bundle on-site and compare it with
the hash above — a match proves they share the same origin.

SHA-256 is a one-way, irreversible hash; publishing the hash leaks no privacy.
