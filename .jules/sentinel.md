## 2024-05-15 - [Identity] Predictable Certificate Serial Numbers
**Vulnerability:** Certificate serial numbers were generated using nanosecond timestamps, making them predictable and guessable.
**Learning:** High-resolution timestamps (nanoseconds) are often mistaken for "unique enough" identifiers but lack cryptographic entropy. This violates RFC 5280 §4.1.2.2 requirements for certificate serial numbers in a PKI.
**Prevention:** Use a CSPRNG (like `ring::rand::SystemRandom`) to generate at least 20 bytes of entropy for certificate serial numbers.
