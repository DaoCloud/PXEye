# 已提交代码同步

[English](README.md) · **简体中文**

`sync.py` 使用增量 Git bundle 将本地已提交版本同步到已有的 SSH 仓库，无需远端访问 GitHub。依赖本机 Python 3、Git、SSH，以及远端 Python 3、Git。SSH 主机密钥需已确认，认证使用现有 SSH 配置。

## 配置

在本地仓库根目录执行一次：

```bash
SYNC_CONFIG="$(git rev-parse --git-path pxeye-code-sync/config.json)"
mkdir -p "$(dirname "$SYNC_CONFIG")"
test ! -e "$SYNC_CONFIG" &&
cp tools/code-sync/config.example.json "$SYNC_CONFIG" &&
${EDITOR:-vi} "$SYNC_CONFIG"
```

配置包含 SSH `host`、`port` 和远端仓库绝对路径 `directory`。配置及日志位于 Git 元数据目录，不纳入源码提交；不保存密码或私钥。

## 使用

在开发机执行，任意工作目录均可：

```bash
python3 /srv/PXEye/tools/code-sync/sync.py
```

默认同步已提交的 `HEAD`。`--ref <commit>` 可选择已提交版本，`--config <path>` 可选择其他目标配置，`--check` 仅检查。

## 执行规则

脚本打印四个阶段：检查两端状态、创建增量包、传输并快进更新、验证目标提交和干净工作区。无变化时直接输出 `SYNC_UP_TO_DATE`，不传输文件。常规同步只建立两次 SSH 连接，不逐文件传输或校验。

- 未提交内容不进入同步包；无需清理开发机的其他改动。
- 远端必须是仓库根目录、与本地 origin 一致且工作区干净。目标提交必须是远端当前版本的后继。
- 远端有改动、历史分叉或同步期间发生变化时停止，不自动 stash、reset 或覆盖。修复原因后执行原命令。
- 工作目录外的配置、镜像和构建产物不受影响。脚本不推送 GitHub、不构建、不部署，也不运行远端应用代码。

每次日志保存在 `git rev-parse --git-path pxeye-code-sync/logs` 指向的目录中。失败时保留远端 Git 元数据目录内本次 bundle，供排查使用。
