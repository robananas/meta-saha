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

## ARM64 Container Artifact Promotion

When an ARM64 container can be built natively on the local Apple Silicon Mac, prefer a build-once, promote-the-same-artifact workflow.

- Build locally with explicit `--platform linux/arm64` when the parent image and build context are available and the build does not require remote-host-only assets.
- Treat Mac build success as an image build result, not as Jetson runtime validation. Validate CUDA/NVIDIA runtime, mounts, readiness, resource use, rollback, and the affected user workflow on the target board.
- Before board deployment, record the image ID, architecture, parent image, Dockerfile/context, archive size, and SHA-256. Verify the archive again on the board before loading it.
- Preserve the currently deployed image under a clear rollback tag and deploy through the normal launcher, Compose, and systemd paths.
- After the board passes, copy the exact board-tested archive into the expected `downloads/` path on `zyk@10.30.32.19`; verify the source and destination SHA-256 match exactly.
- Do not rebuild the image on the packaging host merely to create the packaging input. Rebuild there only when promotion is impossible or the build depends on remote-only inputs, and then repeat board validation for that new artifact.
- Require a reproducible Dockerfile and minimal complete context for every packaged image. Never package an image whose only provenance is a board-side `docker commit`.
- Validate that the promoted archive contains only the intended tag/manifest and reports `arm64` before running the focused recipe or image packaging task.

## Validated Container Publication and Deployment Sync

After a container image passes target-board validation, publication and deployment synchronization are part of completing the task, not optional follow-up.

- Push the exact board-tested image to `registry.cn-beijing.aliyuncs.com/roban` using an immutable dated/versioned tag; never reuse or overwrite a validated tag.
- Record and verify the registry digest. The pushed image ID/platform must match the board-tested artifact; do not rebuild before publishing.
- Keep the verified offline tar in the expected Yocto `downloads/` path and verify its SHA-256 after transfer.
- Update the Yocto preload/tag/archive contract and the Ubuntu 22.04 and 24.04 one-click deployment scripts in the same change. Deployment scripts should resolve validated application images to immutable registry digests.
- Run focused Yocto packaging plus Ubuntu 22/24 deployment contract tests after updating image references.
- Never store registry passwords or auth JSON in the repository. Use the existing Docker credential store or an explicitly supplied external auth file.
- Report the registry reference, registry digest, offline archive SHA-256, Yocto packaging result, and Ubuntu 22/24 script validation.

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

## Line Endings and Formatting

Prevent functional edits from producing unrelated whole-file line-ending changes.

- Preserve each existing file's current line-ending style when making localized edits. Do not silently convert CRLF to LF or LF to CRLF.
- New text files must use LF unless a platform or generated-file contract explicitly requires CRLF.
- Never normalize an entire existing file merely because mixed or CRLF line endings were discovered during another task.
- If line-ending normalization is required, perform it as a separate, explicit task and keep it separate from functional changes so the diff remains reviewable.
- Before using a formatter or bulk rewrite, confirm it will not change line endings or reformat untouched parts of the file. Limit formatting to files intentionally edited.
- After editing, inspect the focused diff for unexpected whole-file churn and run `git diff --check`. If a small logical change appears as a full-file replacement, restore the original line-ending style before continuing.
- Do not use broad newline replacement as a workaround for patch or lint failures. Match the file's existing bytes and make the smallest targeted edit.
