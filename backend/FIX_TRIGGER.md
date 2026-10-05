# CI trigger commit

Trivial file whose push triggers cargo-test + anchor-build on the patched tree.

The actual fix (b32fe585 - mint1.rs instructions sysvar changed from
`Sysvar<Instructions>` to an address-checked `UncheckedAccount`) was pushed by
the fix-ix-sysvar workflow using GITHUB_TOKEN, and token pushes do not trigger
workflow runs. This user-token push re-runs CI over the fixed source.
