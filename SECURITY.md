# Security

**English** · [简体中文](SECURITY.zh-CN.md)

PXEye can change hardware addresses, power and boot settings, write disks and initiate NICo Instance reclamation. Its current single-operator model assumes a trusted management environment.

## Reporting a vulnerability

A private security-reporting channel has not yet been configured. Before public release, maintainers must add one and update both language versions of this policy. Until then, do not include credentials, customer details or sensitive exploit material in public issues. Share sensitive reports only through a privately agreed maintainer channel.

## Runtime boundary

- Put the operator interface behind a controlled management network and TLS entry point or trusted identity proxy.
- Use a dedicated Core mTLS identity and verify the Core certificate chain and hostname.
- Make the BMC certificate policy a site decision; always separately verify device serial and management MAC.
- Run with non-root identity, a read-only root filesystem and restricted capabilities.
- Review the target identity, operation scope and occupancy before hardware writes.

The current service does not provide complete multi-user RBAC or untrusted tenant isolation. It should not be directly exposed to a public network.

## Sensitive data and backups

Keep Core/BMC/SSH keys, certificates, operator credentials, tokens, operational inventories, raw console logs, installer inputs and SQLite data outside Git and container images. Store runtime credentials in restricted files or mounted Secrets.

Protect backups of `/data` and `/materials`: task and identity files can contain sensitive operational data. A consistent SQLite backup must account for WAL writes. Replacing a container preserves data only when the persistent volumes are retained.

See the [deployment guide](docs/deployment.md) for credential filenames, mount paths and update behavior.
