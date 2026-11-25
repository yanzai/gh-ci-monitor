# gh-ci-monitor

一个小型、可自恢复的 GitHub CI 运行状态监测工具——同时支持 **GitHub Actions Run** 与 **GitHub Commit Status**（如外部 Gitea Actions / Jenkins 等回写的状态与失败摘要评论）。

它的目标不是替代 GitHub CLI，而是解决两个实际问题：
1. 长时间使用 `gh run watch` 时，**watch 进程/session 的生命周期与 GitHub Actions 真实状态不一定可靠同步**，在远程 Agent / SSH / MCP 环境中可能卡住不收口；
2. 当仓库采用「GitHub 主代码 + 外部 CI（如 Gitea Actions）回写 GitHub Commit Status」模式且关闭 GitHub Actions 时，云端 Agent 仍可通过原生 GitHub 接口（`--ref HEAD` / `--commit SHA`）统一监测进度、成败与失败日志摘要，**无需暴露外部 CI 凭据**。

`gh-ci-monitor` 不长期持有 `gh run watch`。它反复执行彼此独立、带硬超时的单次 `gh` 查询：

```text
# 按 RUN_ID 监测 GitHub Actions（原模式，完全向后兼容）
gh run view <RUN_ID> --json status,conclusion,jobs,url

# 按 --ref / --commit 自动监测（优先 GitHub Actions，若无则监测 GitHub Commit Status）
gh api repos/<OWNER>/<REPO>/actions/runs?head_sha=<SHA>
gh api repos/<OWNER>/<REPO>/commits/<SHA>/status
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
# 1. 按 GitHub Actions RUN_ID 监测（原模式）
./gh-ci-monitor 123456789 --repo OWNER/REPO

# 2. 按当前 HEAD / 分支 / 提交自动监测（兼容 GitHub Actions 与外部 CI Commit Status）
./gh-ci-monitor --ref HEAD
./gh-ci-monitor --ref main --repo OWNER/REPO --mode status --context-prefix gitea-ci
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
usage: gh-ci-monitor [-h] [--repo OWNER/REPO] [--ref REF] [--commit SHA]
                     [--mode {auto,actions,status}] [--wait-start SECONDS]
                     [--context-prefix PREFIX] [--failure-marker MARKER]
                     [--no-failure-comment]
                     [--interval SECONDS] [--timeout SECONDS]
                     [--query-timeout SECONDS] [--max-backoff SECONDS]
                     [--heartbeat SECONDS] [--version]
                     [RUN_ID]
```

主要参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `RUN_ID` | 可选 | GitHub Actions run ID（与 `--ref` / `--commit` 二选一） |
| `--ref` | 无 | Git ref（如 `HEAD`、`main`、tag），解析后自动监测 Actions 或 Commit Status |
| `--commit` | 无 | 显式 40 位提交 SHA |
| `--mode` | `auto` | `--ref`/`--commit` 时的监测模式：`auto`（先查 Actions 再查 Commit Status）、`actions`、`status` |
| `--wait-start` | 45s | 等待 Webhook/外部 CI 首次写入 Run 或 Commit Status 的宽限时间 |
| `--context-prefix` | 空 | 仅关注指定前缀的 Commit Status（如 `ci /`、`gitea-ci`） |
| `--failure-marker` | `<!-- ci-failure` / `<!-- gitea-ci-failure` | 匹配失败摘要 Commit Comment 的标记前缀，可自定义以适配任意外部 CI |
| `--no-failure-comment` | 关闭 | 设为 true 时，Commit Status 失败不再拉取并打印失败 Commit Comment 摘要 |
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
