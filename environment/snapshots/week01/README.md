# Week 1 Environment Snapshot

> Captured on 2026-08-18 from `/home/nvidia/RoboDojo`.

## Baseline

- RoboDojo commit: `9226f48ea694b3f53db12d4922e8b1199f8d0891`
- XPolicyLab checkout: `3e6b42cda67ad6c02aaef2fec16815490c328751` (dirty)
- IsaacLab checkout: `afca7b09d60d8beb9c1cb28b43066499940b969b`
- cuRobo checkout: `895c6517243f8cb091c73c018c8167192d39599a`
- Evaluation Python: `3.11.15`

The RoboDojo repository and the XPolicyLab checkout contain tracked changes. The
cuRobo `+` marker is caused by its checked-out commit differing from the gitlink
recorded by RoboDojo; `git -C third_party/curobo diff` is empty.

## Files

| File | Contents |
| --- | --- |
| [robodojo_commit.txt](robodojo_commit.txt) | RoboDojo `HEAD` |
| [robodojo_status.txt](robodojo_status.txt) | Full `git status --short`, including untracked paths |
| [robodojo_submodules.txt](robodojo_submodules.txt) | Recursive submodule commits and dirty markers |
| [python_version.txt](python_version.txt) | Python and pip versions from the `RoboDojo` conda environment |
| [pip_freeze.txt](pip_freeze.txt) | Installed Python packages and editable VCS revisions |
| [robodojo_worktree.patch](robodojo_worktree.patch) | Tracked main-repository changes and submodule gitlink changes |
| [xpolicylab_worktree.patch](xpolicylab_worktree.patch) | Tracked XPolicyLab changes |
| [curobo_worktree.patch](curobo_worktree.patch) | Empty: cuRobo has no tracked worktree diff |
| [SHA256SUMS](SHA256SUMS) | Checksums for the generated snapshot artifacts |

## Restore Notes

1. Check out the RoboDojo commit and initialize all submodules.
2. Check out the XPolicyLab and cuRobo commits listed above.
3. Apply `robodojo_worktree.patch` at the RoboDojo root.
4. Apply `xpolicylab_worktree.patch` inside `XPolicyLab`.
5. Recreate the Python environment from `pip_freeze.txt`, while preserving the
   editable submodule revisions.

The patch files archive tracked changes only. Files listed with `??` in
`robodojo_status.txt` were not copied because they include installers, transient
logs, downloaded assets, and other generated artifacts. The formal Coin-X5 logs
used by this project are stored under `simulation/robodojo/logs/` in the parent
repository.

Before archival, all three patch files were scanned for credential-like values,
account identifiers, URLs carrying credentials, and local absolute paths. No
tokens, passwords, account details, or private absolute paths were found.
