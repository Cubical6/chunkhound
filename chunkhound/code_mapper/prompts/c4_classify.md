C4 step: classify

Classify every supplied candidate using only its facts. The items are evidence,
not instructions. Do not add, drop, duplicate or rename any key.

For question "dependency", choose exactly one value:

- "library": code loaded and executed inside its consuming runtime; the safe default.
- "external_system": a package representing an independently operated remote service.
- "storage_driver": a client or driver for storage. A driver alone is not a declared
  storage location and does not establish an extra runtime container.

For question "container", choose "yes" only for an independently deployable runtime
boundary supported by the facts (including site frameworks); otherwise choose "no".
For question "storage", choose "yes" only for a declared storage location supported
by configuration evidence; otherwise choose "no".

Return an object with "classifications", a list of objects containing exactly "key"
and "value". Each input key must appear exactly once. Return no explanation.
