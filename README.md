# gh-ci-monitor

一个小型、可自恢复的 GitHub Actions CI 运行状态监测工具。

它的目标不是替代 GitHub CLI，而是解决长时间使用 `gh run watch` 时可能遇到的一个实际问题：**watch 进程/session 本身的生命周期与 GitHub Actions 的真实状态不一定可靠同步**。在远程 Agent、SSH、MCP 或其他自动化环境中，这可能表现为 CI 已经成功或失败，但监测流程仍像“卡住”一样没有收口。

`gh-ci-monitor` 不长期持有 `gh run watch`。它反复执行彼此独立、带硬超时的：

```text
gh run view <RUN_ID> --json status,conclusion,jobs,url
```

因此任何一次查询超时、空响应、JSON 异常或 GitHub API 短暂失败都只是一次可恢复的采样失败，不会污染下一次查询。

## 特性

- 每次 `gh` 查询都有独立硬超时；
- 每次轮询都会启动一个新的 `gh` 进程，不复用坏掉的 watch/session；
- 空响应、JSON 解析失败、CLI/API 瞬时错误自动退避重试；
- 退避有上限，不会无限增长；
- 只在 run/job 状态变化时输出，默认每 5 分钟补一条 heartbeat；
- 整体监测有 deadline，到期明确退出，不会无限挂住；
- run 一旦 `completed` 就立即退出；
- `success` 返回 0，CI 失败/取消等返回 1，便于脚本和 Agent 继续处理；
- 默认不回显 `gh` 的 stderr，降低鉴权/请求细节被写入日志的风险；
- 主实现仅使用 Python 标准库，无第三方 Python 包依赖；
- Linux、macOS、Windows 均可使用。

## 依赖

- Python 3.9+
- [GitHub CLI (`gh`)](https://cli.github.com/)
- 已完成 `gh auth login`，或以其他方式为 `gh` 提供有效认证

不依赖 `jq`、GNU `timeout` 或第三方 Python 库。

## 使用

### Linux / macOS

```bash
chmod +x gh-ci-monitor
./gh-ci-monitor 123456789 --repo OWNER/REPO
```

可选安装到用户 PATH：

```bash
install -m 755 gh-ci-monitor ~/.local/bin/gh-ci-monitor
```

之后：

```bash
gh-ci-monitor 123456789 --repo OWNER/REPO
```

### Windows PowerShell

```powershell
python .\gh-ci-monitor 123456789 --repo OWNER/REPO
```

如果当前目录本身就是对应 Git 仓库，可以省略 `--repo`，交给 `gh` 从当前仓库推断。

## 参数

```text
usage: gh-ci-monitor [-h] [--repo OWNER/REPO] [--interval SECONDS]
                     [--timeout SECONDS] [--query-timeout SECONDS]
                     [--max-backoff SECONDS] [--heartbeat SECONDS]
                     [--version]
                     RUN_ID
```

主要参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `RUN_ID` | 必填 | GitHub Actions run ID |
| `--repo` | 当前仓库 | `OWNER/REPO` |
| `--interval` | 15s | 正常轮询间隔 |
| `--query-timeout` | 20s | 单次 `gh` 查询硬超时 |
| `--max-backoff` | 60s | 连续瞬时故障的最大退避 |
| `--heartbeat` | 300s | 状态长期不变时的存活输出；`0` 关闭 |
| `--timeout` | 3600s | 整个监测流程的最大持续时间 |

例如：

```bash
gh-ci-monitor 123456789 \
  --repo OWNER/REPO \
  --interval 10 \
  --query-timeout 20 \
  --heartbeat 180 \
  --timeout 7200
```

## 输出示例

```text
[2026-09-29 09:18:57+0800] run=in_progress/- | test=completed/success | build linux=in_progress/-
[2026-09-29 09:20:12+0800] run=completed/success | test=completed/success | build linux=completed/success
[ci-monitor] completed: success https://github.com/owner/repo/actions/runs/123456789
```

如果查询过程临时失败：

```text
[ci-monitor] query failed (gh query exceeded 20s; streak=1); retry in 15s
```

下一轮会重新启动一个全新的 `gh run view` 查询。

## 退出码

| code | 含义 |
|---:|---|
| `0` | run 已完成且 conclusion 为 `success` |
| `1` | run 已完成，但 conclusion 不是 `success` |
| `2` | 参数或本地依赖错误 |
| `3` | 达到整体监测 deadline |
| `130` | 用户中断（Ctrl-C） |

瞬时网络/API/JSON 错误不会立即退出，而是在 deadline 内自动恢复。

## 为什么不用长期 `gh run watch`

`gh run watch` 对人在普通终端里观察 CI 很方便，但在自动化 Agent、远程 shell、工具 session 等环境中，存在两个不同状态源：

1. GitHub Actions run/job 的真实状态；
2. 本地长生命周期 `gh run watch` 进程/session 的状态。

后者如果没有及时退出或 session 状态没有及时刷新，就可能让上层自动化误以为 CI 仍在运行。

本工具刻意不维护这种长连接状态：**GitHub 上的 run 状态才是唯一权威状态，每次查询都是一次可丢弃、可重建的采样。**

## 安全与隐私

- 工具不会主动读取或打印 token；认证完全交给 GitHub CLI。
- 默认不会回显 `gh` 的 stderr，避免错误响应中的请求细节进入日志。
- `--repo`、run ID、job 名称和 GitHub 返回的 run URL 会出现在正常输出中；不要把包含私有仓库信息的日志公开发布。
- 如果需要调试 `gh` 本身，请直接单独运行 `gh run view`，并自行评估其输出是否适合公开。

## Legacy Bash 版本

`legacy/gh-ci-monitor.sh` 保存了最初的 Bash 实现作为历史参考。它依赖 Bash、Python 3 和 GNU `timeout`，因此不推荐作为跨平台主版本。

## 开发与测试

```bash
python3 -m unittest discover -s tests -v
python3 ./gh-ci-monitor --help
python3 ./gh-ci-monitor --version
```

仓库 CI 会在 Linux、macOS 和 Windows 上执行这些测试。

## License

MIT，见 [`LICENSE`](LICENSE)。
