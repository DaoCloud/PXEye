# Committed code synchronization

**English** · [简体中文](README.zh-CN.md)

`sync.py` sends an incremental Git bundle to an existing SSH checkout without requiring remote GitHub access. Requirements: local Python 3, Git and SSH; remote Python 3 and Git. The SSH host key must already be trusted, and authentication uses existing SSH settings.

## Configuration

Run once from the local repository root:

```bash
SYNC_CONFIG="$(git rev-parse --git-path pxeye-code-sync/config.json)"
mkdir -p "$(dirname "$SYNC_CONFIG")"
test ! -e "$SYNC_CONFIG" &&
cp tools/code-sync/config.example.json "$SYNC_CONFIG" &&
${EDITOR:-vi} "$SYNC_CONFIG"
```

Configure the SSH `host`, `port` and absolute remote repository `directory`. Configuration and logs remain in Git metadata, outside source control. Do not store passwords or private keys in the configuration.

## Usage

Run on the development host from any working directory:

```bash
python3 /srv/PXEye/tools/code-sync/sync.py
```

The default revision is committed `HEAD`. Use `--ref <commit>` for another committed revision, `--config <path>` for another target, or `--check` for a read-only check.

## Behavior

Four stages report source/target checks, incremental bundle creation, transfer and fast-forward update, and final commit/clean-tree verification. An unchanged target prints `SYNC_UP_TO_DATE` without transfer. A normal update uses two SSH connections and does not transfer or hash individual checkout files.

- Uncommitted local changes are excluded and can remain in place.
- The remote directory must be a clean repository root with the same origin. The target revision must descend from the current remote commit.
- Dirty, diverged or concurrently changed remote checkouts stop the operation. No automatic stash, reset or overwrite occurs. Fix the cause and rerun the command.
- External configuration, images and build artifacts remain untouched. Synchronization does not push to GitHub, build, deploy or execute remote application code.

Logs are stored under the directory returned by `git rev-parse --git-path pxeye-code-sync/logs`. Failed remote bundles remain in Git metadata for investigation.
