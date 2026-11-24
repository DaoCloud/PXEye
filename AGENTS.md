# PXEye repository workflow

- Treat this repository as the only source of PXEye application code. Do not edit files in a
  running container or maintain a separate site copy of the source.
- Complete each coherent change as a Git commit before building an image. Build and deploy only
  from a clean, committed tree.
- Commit every completed code change before handing the task back, including UI text changes;
  do not leave completed work only in the working tree. Stage only task-related files, preserve
  unrelated changes, and report the commit SHA. A commit does not imply a push or deployment;
  report those separately and perform them only within the user's authorized scope. If committing
  is blocked, state the blocker and the remaining uncommitted files explicitly.
- Tag deployed images with the application version and short Git SHA. Pass the full commit SHA as
  `VCS_REF` so the OCI image metadata records its source revision.
- Keep site addresses, credentials, inventories, runtime databases, and other private operational
  data out of this repository.
- Follow the repository's bilingual documentation policy for public documentation changes.

## Local branch lifecycle

- `main` is the only local integration, deployment and offline-package baseline. Build from a
  clean committed `main` tree or an archive of its exact commit; never deploy a repair branch
  merely because its worktree is convenient or was deployed successfully before.
- Keep only `main` and the explicitly retained `rack-operations` development branch as long-lived
  local branches. `rack-operations` contains later field-development work: do not merge, rebase,
  build, deploy, delete or otherwise modify it unless the user explicitly asks.
- A temporary repair, performance, deployment-pin or integration branch must be reconciled into
  `main` when its task is complete. Before deleting it, inspect its worktree and `git cherry -v
  main <branch>`; preserve dirty work and account for every unique commit. Superseded image-pin
  commits may be intentionally excluded, but record that decision.
- After reconciliation, remove the clean temporary worktree and local branch. Do not leave a
  second persistent checkout as an accidental build source. Creating a temporary worktree for a
  conflict-safe merge is allowed; remove it in the same task.
- A merge, commit or local branch deletion does not imply pushing. Push `main` or any retained
  development branch only when the user explicitly requests it.

## Development deployments and offline bundles

Development is the default. A deployment does not trigger a bundle; a bundle does not trigger a
deployment or create a release. Do not require a Git tag, an application or Chart version bump,
or manual audit commands from the operator for each iteration.

1. **Build what changed.** For a PXEye-only change use `make pxeye-images`, commit the resulting
   unique image reference in `charts/pxeye/values.yaml`, and reuse the pinned Core and boot
   materials. For changes to Core, libredfish or a Scout/Boot recipe, rebuild the affected
   artifacts and update their pins following the [source build guide](docs/source-build.md).
   Keep the application source commit distinct from the commit that pins the delivery inputs.
2. **Finish a deployment with a receipt.** Keep one dated record per target and deployment,
   outside public Git: target/context/namespace, source and configuration commits, deployed
   image references and observed platform digests, boot-material lock references, readiness and
   data preservation outcome. Record what was actually checked. A failed or partial rollout
   never replaces the last successful receipt.
3. **Package the deployment, not the branch tip.** On a bundle request, start from the selected
   target's last successful receipt and its clean configuration commit. Check the target has not
   drifted. If the receipt is missing, establish it once from the running target and matching
   committed inputs; do not redeploy just to create a record. If the target runs A and the branch
   is now at B, package A. Do not silently package B, fall back to another environment, or edit an
   old lock to match new images.
4. **Verify before handing off.** Use `make bundles`. Match the committed inputs, the receipt,
   and the archive manifests by platform digest for images and SHA256 for shipped boot files.
   For payloads not exercised on the target, verify against their pinned source and report that
   scope separately. A missing or mismatched required digest blocks delivery: name the component
   and the missing or different evidence. Do not include site uploads, credentials or runtime data.
5. **Identify both archives with one development batch.** Choose `BUNDLE_VERSION` once, e.g.
   `v0.22.16-dev.20261118.1110-fed6729` (base version, Shanghai build date/time, packaging SHA).
   Reuse it for a retry with identical inputs; allocate a new unused ID for a new build, adding
   a sequence if needed. Deliver `pxeye-offline-<BUNDLE_VERSION>-linux-amd64.tar.gz` and
   `pxeye-tools-<BUNDLE_VERSION>-linux-amd64.tar.gz`. Record the deployment receipt, both names,
   sizes and SHA256s together. Never replace different bytes under an existing delivery name.

**Current tooling:** `make bundles` does not select a deployment or produce these delivery names
automatically. Until it does, the agent performs the [version audit](tools/version-audit/README.md)
and the checks above, supplies the batch ID, and creates the named delivery copies from verified
`bundle.tar.gz` and `onsite-tools.tar.gz`. Keep the original build outputs for resume; verify the
delivery copies against their original hashes. A full source lock is valid only for the exact
combination it records. After a PXEye-only update, use the new PXEye digest plus verified pins
for reused materials; do not pass the previous full lock as evidence for the new combination.

## Rules by area

- Application code, protected installation and discovery paths, naming:
  [src/pxeye/AGENTS.md](src/pxeye/AGENTS.md).
- Documentation layout, naming and bilingual policy: [docs/AGENTS.md](docs/AGENTS.md).
- Design documents and interaction rules: [docs/design](docs/design/README.md).

