---
name: claude-collaboration
description: |
  Claude collaboration for expert advice and complex tasks.
  Use when: architecture advice, deep technical insight, or complex refactoring is needed.
  调用 Claude 进行深度技术咨询或复杂任务处理。
---

# Claude 协作指南

## 角色定位

Claude 是 CCG 流程中的 **高阶专家顾问**。当 Gemini (架构师) 遇到以下情况时，建议调用 Claude：

- **深度架构建议**：需要对系统架构进行深度优化或重构时。
- **复杂逻辑处理**：遇到极其复杂的算法或业务逻辑，需要 Claude 特有的推理能力时。
- **第二意见**：在重大决策前，需要一个独立的专家视角进行评估。

## 调用原则

1. **按需调用**：Claude 能力极强但调用成本（时间/Token）相对较高，优先使用 Coder 处理常规任务。
2. **上下文充分**：调用时请提供完整的文件背景、需求描述和具体的咨询点。
3. **保持 Session**：在连续对话中务必传递 `SESSION_ID`。

## 常用指令

- `/claude "请分析这个模块的潜在性能瓶颈，并给出优化建议"`
- `/claude "我想将这个同步流程改为异步，请提供一个重构方案"`

## 详细参数

详见 [claude-guide.md](claude-guide.md)