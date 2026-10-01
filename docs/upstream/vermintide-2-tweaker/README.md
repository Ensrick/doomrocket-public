# Working Tweaker workflow: exact source copy

Copied at the user's direction on September 13, 2026 from
`Ensrick/vermintide-2-tweaker`, commit `a55228bcea2b1aef08bd10e2fa577943dadf22a3`.
Every source file here is byte-for-byte unchanged. `COPY_MANIFEST.json` records
its SHA-256. This directory preserves the working method, not a rewritten
Warlock-specific release implementation.

Read [PROJECT_STANDARDS.md section 6.6](PROJECT_STANDARDS.md#66-ship-doctrine-keyed-off-the-mod_version-suffix-canonical-2026-07-01)
for the owning build/deploy/upload procedure, [CLAUDE.md](CLAUDE.md) for the
non-negotiables, and [portable setup](docs/PORTABLE_SETUP.md) for launcher and
Steam recovery instructions.

The exact [ship implementation](tools/ship/ship.ps1), claim broker, transaction
lease, upload observer, release publisher, receipt helpers and launcher resolver
are copied here for reuse and comparison. Their original repository coordinates,
inventory, paths and dependencies are preserved. They are not standalone scripts:
running this copy from a Warlock checkout does not register Warlock in Tweaker's
inventory or configure its GitHub publication receipts. Do not execute it here
or substitute Warlock for a Tweaker mod ID.

Use [the Warlock release guide](../../RELEASE_CHANNELS.md) for the project mapping.
