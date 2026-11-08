# PXEye repository workflow

- Treat this repository as the only source of PXEye application code. Do not edit files in a
  running container or maintain a separate site copy of the source.
- Complete each coherent change as a Git commit before building an image. Build and deploy only
  from a clean, committed tree.
- Tag deployed images with the application version and short Git SHA. Pass the full commit SHA as
  `VCS_REF` so the OCI image metadata records its source revision.
- Record the commit, immutable image reference, target environment, deployment health, and data
  preservation result for each deployment.
- Keep site addresses, credentials, inventories, runtime databases, and other private operational
  data out of this repository.
- Follow the repository's bilingual documentation policy for public documentation changes.

