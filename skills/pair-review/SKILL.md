---
name: pair-review
description: Use Pair Review when the user asks for proposal-first coding, candidate review, VS Code approval, or says to use pair-review; submit complete candidates through MCP and collaborate only on published feedback without editing reviewed source files.
---

# Pair Review

通过 `pair-review` MCP server 提出完整候选，由用户在当前 VS Code 窗口审核。MCP 工具名为 `propose`、`feedback`、`wait`、`reply` 和 `reply_thread`。

## 提出一个逻辑修改

1. 确认 `pair-review` MCP server 已连接。未连接时请用户安装或启用本扩展，不要退回直接写源文件的流程。
2. 读取最新源文件，把**修改后的完整文件**写入项目内 `.pair-review/candidates/`。每个提案只包含一个可理解的逻辑修改。
3. 调用 `propose`：`target` 是项目相对源文件路径，`candidate` 是完整候选文件路径，`title` 描述意图，`agent` 使用当前 agent 名称。
4. 返回提案 ID、目标和修改目的。VS Code 插件会自动打开审阅面板和完整 diff；不要运行 `code`、`code -n`、`open -a` 或切换工作区。

候选文件存在不代表修改已授权。源文件、测试、格式化和其他脚本都不能绕过审阅写入目标。

## 等待已发布反馈

1. 调用 `feedback` 获取 `revision`，再调用 `wait`，使用 `timeout: 60`、该 `revision` 作为 `since`，并保持 `next_only: true`。
2. `waitStatus: "timeout"` 只表示没有新消息；继续等待，不能当成批准。全部 hunk 已决定后也继续等待后续问题，直到用户明确要求停止或执行环境无法继续。停止持续等待时明确说明。
3. 只根据 `feedback` 中的已提交决定和已发布评论继续工作。Accept/Reject 草稿、`inlineDrafts` 和 `state` 属于审核侧私有状态，不读取、不修改、不据此行动。
4. 用户可以只提交一个 hunk，也可以撤回先前提交的决定。每次继续修改前重新读取 `feedback` 和当前源文件。

## 回复与修订

- 评论含 `threadId` 时调用 `reply_thread`，回复到准确讨论串；结合 `side`、`startLine`、`endLine` 和 `quotedCode` 理解代码位置。面板 hunk 或总体讨论使用 `reply`。
- 先回答问题，再决定是否需要新候选。回复后重新读取 `feedback` 获取新 revision，继续等待；自己的回复不是新的用户任务。
- 修订时重新读取当前源文件，生成新的完整候选并调用 `propose`。标题注明修订哪个旧提案，提醒用户审核新提案，避免接受过时版本。旧提案和讨论保持独立。
- 多个提案仍活跃时轮流读取它们的 `feedback`，避免只监听最新提案而漏掉旧讨论串。

未收到具体开发任务时等待用户，不自行挑选代码修改。
