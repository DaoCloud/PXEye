# Preparing a public release

**English** · [简体中文](publishing.zh-CN.md) · [Documentation](README.md)

## Repository boundary

The public repository is [SSmallMonster/PXEye](https://github.com/SSmallMonster/PXEye). In the original development workspace, `services/os-install-console/` is its independent repository root. The surrounding workspace includes upstream repositories, environment records and private material; it is not a single PXEye repository.

Keep the public source, bilingual documentation, brand assets, deployment skeleton and authored view dataset. Exclude upstream checkouts, environment-specific manifests, secrets, SQLite databases, OS media, raw console logs, operational inventories and third-party binaries. Historical environment notes stay outside this project; the public changelog records capability milestones.

## Release preparation

1. Retain the selected [Apache-2.0 license](../LICENSE) and third-party notices.
2. Confirm project-name and package availability, and preserve the independent-project attribution.
3. Configure private vulnerability reporting and update the security documents in both languages.
4. Inspect source and any imported Git history for credentials, private inventories and environment data. Ignore rules do not sanitize existing history.
5. Review licenses and notices for dependencies, fonts, icons and other redistributed assets.
6. Build from a clean checkout with compatible, verified runtime binaries and site configuration.
7. Validate only the authorized deployment and hardware paths, labeling the evidence precisely.
8. Check both language versions, local links and screenshot provenance before tagging a release.

## Initial scope

The initial release should be presented as a technical preview of NICo resource views, device discovery and planning, network and OS-material management, installation profiles and a serial installation workflow with logs, recovery and acceptance records.

Do not claim multi-user RBAC, distributed execution, universal hardware compatibility or a production SLA. The [reference screenshots](reference-cluster.md) demonstrate the interface, not a deployed customer cluster or successful GB200 installation.
