# Development Rules

## Build Environment

- The actual `meta-saha` build workspace is `zyk@10.30.32.19:/home/zyk/Desktop/meta-saha`.

## Build Workspace Search Safety

The remote build workspace contains very large and potentially problematic generated trees.

- Never run full recursive `rg`, `rglob`, `find`, IDE indexing, or equivalent searches across the build machine's `build/` or `downloads/` directories. These scans can exhaust kernel resources and freeze `10.30.32.19`.
- Prefer exact known paths, BitBake variables/log paths, bounded `ls`, explicit filenames, and narrowly scoped searches with a limited depth.
- If a search under `build/` or `downloads/` is unavoidable, first restrict it to the smallest recipe, machine, task, or artifact subtree and add explicit glob exclusions for unrelated generated trees and mounts.
- Before traversing an unfamiliar generated path, inspect its immediate mount and directory boundaries. Avoid or unmount a known problematic/stale mount before searching it.
- Do not use broad repository-root searches on the build machine when the pattern can enter `build/` or `downloads/`; explicitly exclude both directories.

## Temporary Changes on a Test Board

When testing a change directly on a Saha/Roban board, keep the deployed temporary change and the corresponding `meta-saha` source change identical.

- Treat `meta-saha` as the source of truth. A file modified directly on a board is temporary and must not become the only copy of a fix.
- Before changing a board file, identify its source recipe/file in `meta-saha`, download or checksum the deployed version, and create a dated or clearly named backup on the board.
- Make the smallest testable board change. Record the exact board path and its corresponding repository path.
- After the board test succeeds, apply the same effective change to `meta-saha`. Account for Yocto behavior: runtime commands such as `systemctl disable` may need an image recipe, package post-install action, preset, or `ROOTFS_POSTPROCESS_COMMAND` rather than a simple recipe-local file deletion.
- Compare the final board file or effective system state against what the updated recipes will generate. Do not report completion based only on similar-looking code.
- Run relevant syntax, lint, recipe/framework, and `git diff --check` validations. When startup or service behavior changes, reboot the board and verify service state, timing, logs, and client reconnection.
- Keep unrelated existing working-tree changes intact. Do not overwrite, restore, stage, or commit them unless explicitly requested.
- Report any board-only artifacts or backups and whether they should be removed after the next image deployment.
