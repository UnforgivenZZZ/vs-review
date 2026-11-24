# Pair Review MCP 0.4.0

用 **Qwen Skill + Python MCP + VS Code 薄宿主**复刻 Pair Review 0.4.0。Agent 只能提交完整候选并读取已发布反馈；用户在当前 VS Code 窗口查看完整 diff、逐行讨论、暂存 Accept/Reject，并通过 Submit 应用修改。

## 架构

```text
Qwen Skill
   │ 约束候选、等待、回复与修订流程
   ▼
Python MCP server ───────┐
 propose / feedback      │ 共享同一 Python core 与 .pair-review 数据
 wait / reply            │
                         ▼
VS Code 薄宿主 ── JSON-lines ── Python review bridge
 Webview / native diff          draft / submit / inline comments
 Comments API                   conflict checks / atomic writes
```

审核规则和文件写入全部在 `src/pair_review/` 的 Python 代码中。`vscode/` 仅适配 VS Code API；保留内嵌窗口和原生 Comments API 必须有一层 JavaScript 宿主，但它不包含另一份审核引擎。

MCP 不暴露 Accept、Reject、Submit 或修改审核草稿的工具，agent 无法通过 MCP 自行批准代码。

## 功能

- 完整原始文件、候选文件和仅含已提交 Accept 的结果预览。
- 一个提案对应一个不可变候选快照，逐 hunk Accept/Reject/Undo。
- 草稿与已提交反馈隔离；支持单处、单讨论串、单条评论或整个提案提交。
- 原始侧和候选侧的行内、多行讨论，保留 `threadId`、行号、侧别及 `quotedCode`。
- Agent `reply_thread` 回复自动出现在原讨论串和审阅面板，无需刷新。
- 独立 Send comment 不提交其他评论或代码决定。
- 提交冲突时保留草稿，不覆盖用户后续修改；新建文件可安全撤回。
- UTF-8、BOM、CRLF、新建空文件、1 MiB 上限、原子写入及中断恢复。
- Pygments 全文语法高亮，跨行注释和字符串在 diff 切片后仍保留上下文。

## 安装

要求：Python 3.10+、Node.js 18+、[uv](https://docs.astral.sh/uv/) 和支持 Comments API 的 VS Code 1.90+。

### 1. 准备 Python 环境

```bash
uv sync
```

`uv run` 也会在首次启动 MCP 或 VS Code bridge 时准备依赖。VS Code 设置 `pairReview.uvPath` 可指定 uv 的绝对路径。

### 2. 安装 Qwen Skill + MCP

```bash
qwen extensions link "/absolute/path/vs-review"
```

确认扩展列出的本地 MCP 启动配置，然后重启 Qwen Code。Skill 注册名为 `vs-review:pair-review`，MCP server 名为 `pair-review`。在目标项目启动 Qwen，`${workspacePath}` 会成为审阅根目录。

### 3. 安装 VS Code 薄宿主

```bash
python3 scripts/package.py
```

在 VS Code 中使用 **Extensions: Install from VSIX…** 安装生成的 `dist/pair-review-mcp-0.4.0.vsix`。Qwen 和 VS Code 必须打开同一个项目根目录。

## 使用

直接要求 agent：

```text
使用 pair-review 修改 src/example.py，把读取和解析拆成两个函数。
```

Agent 的 Skill 会引导它：

1. 将完整候选写入 `.pair-review/candidates/`。
2. 调用 MCP `propose`，源文件保持不变。
3. 当前 VS Code 窗口自动打开审核面板和完整 diff。
4. Agent 通过 `wait` 持续读取已发布反馈，并用 `reply` 或 `reply_thread` 回复。
5. 用户 Submit 后，Python 核心应用接受的 hunk；等待超时、评论或草稿都不构成批准。

### MCP 工具

| 工具 | 用途 |
| --- | --- |
| `propose` | 从完整候选创建单文件提案，不修改源文件 |
| `feedback` | 读取已提交决定和已发布评论 |
| `wait` | 等待指定 revision 之后的新反馈；返回 `waitStatus` |
| `reply` | 回复 hunk 或总体讨论 |
| `reply_thread` | 回复已发布的准确行内讨论串 |

`wait` 默认 `next_only=true`。`waitStatus="timeout"` 不是批准，也不是新反馈。

## 数据与边界

沿用 `.pair-review/proposals/*.dff`、`state/`、`comments/` 和 `candidates/` 布局。`.dff` 是包含原始及候选全文的 JSON，不是 unified diff。建议将 `.pair-review/` 加入目标项目 `.gitignore`。

当前范围与 0.4.0 一致：UTF-8 文本、单文件提案、最多 1 MiB。不支持删除/重命名提案、二进制、权限变更或多文件原子事务。大型复杂 diff 会退化为单块。该协作流程不能强制阻止其他进程直接写文件。

## 开发与验证

```bash
uv sync --extra dev
uv run pytest
npm install --ignore-scripts
npm test
npm run check
npm run test:host
python3 scripts/package.py
```

测试覆盖核心状态机、提交范围、撤回与冲突、行内评论、MCP stdio 握手、bridge 和审阅页 DOM。`test:host` 会打包 VSIX，将其安装到项目内隔离的 extensions/user-data 目录，再用真实 VS Code Extension Host 验证自动审阅、原生 diff、行内提交和代码写入；不会修改日常 VS Code 配置。

需求来源：`Pair_Review_Functional_Spec_v0.4.0.pdf`。未打包原 `core.js` 或 Highlight.js；审核引擎使用官方 Python MCP SDK、Python `difflib` 和 Pygments，非 Python 代码仅承担 VS Code API 与 Webview 交互适配。
