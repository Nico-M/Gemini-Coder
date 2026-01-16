# Claude Tool Guide

Claude 是 CCG (Coder-Codex-Gemini) 流程中的 **高阶专家顾问**。

## 工具参数详情

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `PROMPT` | string | **必填**。发送给 Claude 的指令。 | - |
| `cd` | string | **必填**。工作目录（建议传入当前工作目录）。 | - |
| `SESSION_ID` | string | 可选。会话 ID，用于多轮对话。 | "" |
| `sandbox` | string | 可选。沙箱策略：`read-only`, `workspace-write`, `danger-full-access`。 | `workspace-write` |
| `timeout` | number | 可选。空闲超时（秒）。 | 300 |

## 使用示例

### 1. 技术咨询 (Architecture Advice)

```python
await claude(
    PROMPT="请分析当前项目的目录结构，评价其是否符合典型的 Python 项目最佳实践，并指出不足之处。",
    cd="/path/to/project"
)
```

### 2. 复杂代码实现 (Complex Implementation)

```python
await claude(
    PROMPT="请实现一个支持断点续传的流式文件下载器，要求包含完善的错误处理和重试机制。",
    cd="/path/to/project",
    sandbox="workspace-write"
)
```

## 注意事项

- **写权限**：虽然 Claude 默认为 `workspace-write`，但对于常规的代码修改，建议先咨询 Claude 方案，然后让 **Coder** 执行。
- **并发控制**：避免同时向 Claude 发送多个大型任务。
- **费用考量**：Claude 调用通常涉及更聪明的模型，请在必要时使用。