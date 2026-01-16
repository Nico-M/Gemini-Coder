"""Claude 工具实现

调用 Claude CLI 进行高阶咨询、代码执行或方案探讨。
Claude 在 CCG 流程中担任专家咨询角色。
"""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Dict, Generator, Iterator, Literal, Optional

from pydantic import Field

from ccg_mcp.config import build_claude_env, get_config


# ============================================================================ 
# 错误类型定义
# ============================================================================ 

class CommandNotFoundError(Exception):
    """命令不存在错误"""
    pass


class CommandTimeoutError(Exception):
    """命令执行超时错误"""
    def __init__(self, message: str, is_idle: bool = False):
        super().__init__(message)
        self.is_idle = is_idle  # 标记是否为空闲超时


# ============================================================================ 
# 错误类型枚举
# ============================================================================ 

class ErrorKind:
    """结构化错误类型枚举"""
    TIMEOUT = "timeout"  # 总时长超时
    IDLE_TIMEOUT = "idle_timeout"  # 空闲超时（无输出）
    COMMAND_NOT_FOUND = "command_not_found"
    UPSTREAM_ERROR = "upstream_error"
    JSON_DECODE = "json_decode"
    PROTOCOL_MISSING_SESSION = "protocol_missing_session"
    EMPTY_RESULT = "empty_result"
    SUBPROCESS_ERROR = "subprocess_error"
    CONFIG_ERROR = "config_error"
    UNEXPECTED_EXCEPTION = "unexpected_exception"


# ============================================================================ 
# 指标收集
# ============================================================================ 

class MetricsCollector:
    """指标收集器"""

    def __init__(self, tool: str, prompt: str, sandbox: str):
        self.tool = tool
        self.sandbox = sandbox
        self.prompt_chars = len(prompt)
        self.prompt_lines = prompt.count('\n') + 1
        self.ts_start = datetime.now(timezone.utc)
        self.ts_end: Optional[datetime] = None
        self.duration_ms: int = 0
        self.success: bool = False
        self.error_kind: Optional[str] = None
        self.retries: int = 0
        self.exit_code: Optional[int] = None
        self.result_chars: int = 0
        self.result_lines: int = 0
        self.raw_output_lines: int = 0
        self.json_decode_errors: int = 0

    def finish(
        self,
        success: bool,
        error_kind: Optional[str] = None,
        result: str = "",
        exit_code: Optional[int] = None,
        raw_output_lines: int = 0,
        json_decode_errors: int = 0,
        retries: int = 0,
    ) -> None:
        """完成指标收集"""
        self.ts_end = datetime.now(timezone.utc)
        self.duration_ms = int((self.ts_end - self.ts_start).total_seconds() * 1000)
        self.success = success
        self.error_kind = error_kind
        self.result_chars = len(result)
        self.result_lines = result.count('\n') + 1 if result else 0
        self.exit_code = exit_code
        self.raw_output_lines = raw_output_lines
        self.json_decode_errors = json_decode_errors
        self.retries = retries

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "ts_start": self.ts_start.isoformat() if self.ts_start else None,
            "ts_end": self.ts_end.isoformat() if self.ts_end else None,
            "duration_ms": self.duration_ms,
            "tool": self.tool,
            "sandbox": self.sandbox,
            "success": self.success,
            "error_kind": self.error_kind,
            "retries": self.retries,
            "exit_code": self.exit_code,
            "prompt_chars": self.prompt_chars,
            "prompt_lines": self.prompt_lines,
            "result_chars": self.result_chars,
            "result_lines": self.result_lines,
            "raw_output_lines": self.raw_output_lines,
            "json_decode_errors": self.json_decode_errors,
        }

    def format_duration(self) -> str:
        """格式化耗时为 "xmxs" 格式"""
        total_seconds = self.duration_ms // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}m{seconds}s"

    def log_to_stderr(self) -> None:
        """将指标输出到 stderr（JSONL 格式）"""
        metrics = self.to_dict()
        # 移除 None 值以减少输出
        metrics = {k: v for k, v in metrics.items() if v is not None}
        try:
            print(json.dumps(metrics, ensure_ascii=False), file=sys.stderr)
        except Exception:
            pass  # 静默失败，不影响主流程


# ============================================================================ 
# 命令执行
# ============================================================================ 

@contextmanager
def safe_claude_command(
    cmd: list[str],
    env: dict[str, str],
    cwd: Path | None = None,
    timeout: int = 300,
    max_duration: int = 1800,
    prompt: str = "",
) -> Iterator[Generator[str, None, tuple[Optional[int], int]]]:
    """安全执行 Claude 命令的上下文管理器"""
    claude_path = shutil.which('claude')
    if not claude_path:
        raise CommandNotFoundError(
            "未找到 claude CLI。请确保已安装 Claude Code CLI 并添加到 PATH。"
        )
    popen_cmd = cmd.copy()
    popen_cmd[0] = claude_path

    process = subprocess.Popen(
        popen_cmd,
        shell=False,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        encoding='utf-8',
        errors='replace',
        env=env,
        cwd=cwd,
    )

    thread: Optional[threading.Thread] = None

    def cleanup() -> None:
        """清理子进程和线程"""
        nonlocal thread
        try:
            if process.stdout and not process.stdout.closed:
                process.stdout.close()
        except (OSError, IOError):
            pass
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
        except (ProcessLookupError, OSError):
            pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)

    try:
        if process.stdin:
            try:
                if prompt:
                    process.stdin.write(prompt)
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

        output_queue: queue.Queue[str | None] = queue.Queue()
        raw_output_lines_holder = [0]
        GRACEFUL_SHUTDOWN_DELAY = 0.3

        def is_session_completed(line: str) -> bool:
            try:
                data = json.loads(line)
                return data.get("type") in ("result", "error")
            except (json.JSONDecodeError, AttributeError, TypeError):
                return False

        def read_output() -> None:
            try:
                if process.stdout:
                    for line in iter(process.stdout.readline, ""):
                        stripped = line.strip()
                        output_queue.put(stripped)
                        if stripped:
                            raw_output_lines_holder[0] += 1
                        if is_session_completed(stripped):
                            time.sleep(GRACEFUL_SHUTDOWN_DELAY)
                            break
                    process.stdout.close()
            except (OSError, IOError, ValueError):
                pass
            finally:
                output_queue.put(None)

        thread = threading.Thread(target=read_output, daemon=True)
        thread.start()

        def generator() -> Generator[str, None, tuple[Optional[int], int]]:
            nonlocal thread
            start_time = time.time()
            last_activity_time = time.time()
            timeout_error: CommandTimeoutError | None = None

            while True:
                now = time.time()

                if max_duration > 0 and (now - start_time) >= max_duration:
                    timeout_error = CommandTimeoutError(
                        f"claude 执行超时（总时长超过 {max_duration}s）",
                        is_idle=False
                    )
                    break

                if (now - last_activity_time) >= timeout:
                    timeout_error = CommandTimeoutError(
                        f"claude 空闲超时（{timeout}s 无输出）",
                        is_idle=True
                    )
                    break

                try:
                    line = output_queue.get(timeout=0.5)
                    if line is None:
                        break
                    last_activity_time = time.time()
                    if line:
                        yield line
                except queue.Empty:
                    if process.poll() is not None and not thread.is_alive():
                        break

            if timeout_error is not None:
                cleanup()
                raise timeout_error

            exit_code: Optional[int] = None
            try:
                exit_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                timeout_error = CommandTimeoutError(
                    "claude 进程等待超时",
                    is_idle=False
                )
            finally:
                if thread is not None:
                    thread.join(timeout=5)

            if timeout_error is not None:
                raise timeout_error

            while not output_queue.empty():
                try:
                    line = output_queue.get_nowait()
                    if line is not None:
                        yield line
                except queue.Empty:
                    break

            return (exit_code, raw_output_lines_holder[0])

        yield generator()

    except Exception:
        cleanup()
        raise
    finally:
        cleanup()


def _filter_last_lines(lines: list[str], max_lines: int = 50) -> list[str]:
    import copy
    filtered = []
    for line in lines:
        try:
            data = json.loads(line)
            msg_type = data.get("type", "")
            if msg_type == "user":
                message = data.get("message", {})
                content = message.get("content")
                if isinstance(content, list):
                    data = copy.deepcopy(data)
                    for block in data["message"]["content"]:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            block["content"] = "[truncated]"
                    filtered.append(json.dumps(data, ensure_ascii=False))
                else:
                    filtered.append(line)
                continue
            filtered.append(line)
        except (json.JSONDecodeError, TypeError, AttributeError):
            filtered.append(line)
    return filtered[-max_lines:]


def _build_error_detail(
    message: str,
    exit_code: Optional[int] = None,
    last_lines: Optional[list[str]] = None,
    json_decode_errors: int = 0,
    idle_timeout_s: Optional[int] = None,
    max_duration_s: Optional[int] = None,
    retries: int = 0,
) -> Dict[str, Any]:
    detail: Dict[str, Any] = {"message": message}
    if exit_code is not None:
        detail["exit_code"] = exit_code
    if last_lines:
        detail["last_lines"] = _filter_last_lines(last_lines, max_lines=50)
    if json_decode_errors > 0:
        detail["json_decode_errors"] = json_decode_errors
    if idle_timeout_s is not None:
        detail["idle_timeout_s"] = idle_timeout_s
    if max_duration_s is not None:
        detail["max_duration_s"] = max_duration_s
    if retries > 0:
        detail["retries"] = retries
    return detail


# ============================================================================ 
# Claude System Prompt
# ============================================================================ 

CLAUDE_SYSTEM_PROMPT = "你是一个高阶技术专家和咨询顾问。【角色定位】- 提供深度的技术见解和架构建议 - 能够执行复杂的代码重构或原型开发 - 保持专业、客观、严谨【输出规范】- 仅输出任务结果与必要的改动说明"


# ============================================================================ 
# 主工具函数
# ============================================================================ 

async def claude_tool(
    PROMPT: Annotated[str, "发送给 Claude 的咨询或任务指令"],
    cd: Annotated[Path, "工作目录"],
    sandbox: Annotated[
        Literal["read-only", "workspace-write", "danger-full-access"],
        Field(description="沙箱策略，默认允许写工作区")
    ] = "workspace-write",
    SESSION_ID: Annotated[str, "会话 ID，用于多轮对话"] = "",
    return_all_messages: Annotated[bool, "是否返回完整消息"] = False,
    return_metrics: Annotated[bool, "是否在返回值中包含指标数据"] = False,
    timeout: Annotated[int, "空闲超时（秒）"] = 300,
    max_duration: Annotated[int, "总时长硬上限（秒）"] = 1800,
    max_retries: Annotated[int, "最大重试次数"] = 0,
    log_metrics: Annotated[bool, "是否将指标输出到 stderr"] = False,
) -> Dict[str, Any]:
    """执行 Claude 咨询或任务

    调用 Claude CLI 进行高阶咨询、代码执行或方案探讨。
    """
    metrics = MetricsCollector(tool="claude", prompt=PROMPT, sandbox=sandbox)

    try:
        config = get_config()
        env = build_claude_env(config)
    except Exception as e:
        error_msg = f"配置加载失败：{e}"
        metrics.finish(success=False, error_kind=ErrorKind.CONFIG_ERROR)
        if log_metrics:
            metrics.log_to_stderr()
        result = {
            "success": False,
            "tool": "claude",
            "error": error_msg,
            "error_kind": ErrorKind.CONFIG_ERROR,
            "error_detail": _build_error_detail(error_msg),
        }
        if return_metrics:
            result["metrics"] = metrics.to_dict()
        return result

    cmd = [
        "claude",
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--setting-sources", "project",
    ]

    if sandbox != "read-only":
        cmd.append("--dangerously-skip-permissions")

    cmd.extend(["--append-system-prompt", CLAUDE_SYSTEM_PROMPT])

    if SESSION_ID:
        cmd.extend(["-r", SESSION_ID])

    normalized_prompt = PROMPT.replace('\r\n', '\n').replace('\r', '\n')

    retries = 0
    last_error: Optional[Dict[str, Any]] = None
    all_last_lines: list[str] = []

    while retries <= max_retries:
        all_messages: list[Dict[str, Any]] = []
        result_content = ""
        success = True
        had_error = False
        err_message = ""
        session_id: Optional[str] = None
        exit_code: Optional[int] = None
        raw_output_lines = 0
        json_decode_errors = 0
        error_kind: Optional[str] = None
        last_lines: list[str] = []
        assistant_text_parts: list[str] = []

        try:
            with safe_claude_command(cmd, env, cd, timeout, max_duration, prompt=normalized_prompt) as gen:
                try:
                    for line in gen:
                        last_lines.append(line)
                        if len(last_lines) > 50:
                            last_lines.pop(0)

                        try:
                            line_dict = json.loads(line.strip())
                            msg_type = line_dict.get("type", "")

                            if return_all_messages:
                                if msg_type == "user":
                                    import copy
                                    safe_dict = copy.deepcopy(line_dict)
                                    message = safe_dict.get("message", {})
                                    content = message.get("content")
                                    if isinstance(content, list):
                                        for block in content:
                                            if isinstance(block, dict) and block.get("type") == "tool_result":
                                                block["content"] = "[truncated]"
                                    all_messages.append(safe_dict)
                                else:
                                    all_messages.append(line_dict)

                            if msg_type == "system" and line_dict.get("subtype") == "init":
                                session_id = line_dict.get("session_id")
                            elif msg_type == "assistant":
                                message = line_dict.get("message", {})
                                content = message.get("content")
                                if isinstance(content, list):
                                    for block in content:
                                        if isinstance(block, dict) and block.get("type") == "text":
                                            text = block.get("text", "")
                                            if text:
                                                assistant_text_parts.append(text)
                            elif msg_type == "result":
                                if "result" in line_dict:
                                    result_content = line_dict.get("result", "")
                                if not session_id and "session_id" in line_dict:
                                    session_id = line_dict.get("session_id")
                                if line_dict.get("is_error"):
                                    had_error = True
                                    err_message = line_dict.get("result", "") or line_dict.get("error", "")
                                    error_kind = ErrorKind.UPSTREAM_ERROR
                            elif msg_type == "error":
                                had_error = True
                                error_data = line_dict.get("error", {})
                                err_message = error_data.get("message", str(line_dict))
                                error_kind = ErrorKind.UPSTREAM_ERROR
                        except json.JSONDecodeError:
                            json_decode_errors += 1
                            continue
                except StopIteration as e:
                    if isinstance(e.value, tuple) and len(e.value) == 2:
                        exit_code, raw_output_lines = e.value

            if not result_content and assistant_text_parts:
                result_content = "\n\n".join(assistant_text_parts)

        except CommandNotFoundError as e:
            metrics.finish(success=False, error_kind=ErrorKind.COMMAND_NOT_FOUND, retries=retries)
            if log_metrics:
                metrics.log_to_stderr()
            result = {
                "success": False,
                "tool": "claude",
                "error": str(e),
                "error_kind": ErrorKind.COMMAND_NOT_FOUND,
                "error_detail": _build_error_detail(str(e)),
            }
            if return_metrics:
                result["metrics"] = metrics.to_dict()
            return result

        except CommandTimeoutError as e:
            error_kind = ErrorKind.IDLE_TIMEOUT if e.is_idle else ErrorKind.TIMEOUT
            had_error = True
            err_message = str(e)
            success = False
            all_last_lines = last_lines.copy()
            last_error = {
                "error_kind": error_kind,
                "err_message": err_message,
                "exit_code": exit_code,
                "json_decode_errors": json_decode_errors,
                "raw_output_lines": raw_output_lines,
            }
            break

        if had_error:
            success = False
        if session_id is None:
            success = False
            if not error_kind:
                error_kind = ErrorKind.PROTOCOL_MISSING_SESSION
            err_message = "未能获取 SESSION_ID。\n\n" + err_message
        if not result_content and success:
            success = False
            if not error_kind:
                error_kind = ErrorKind.EMPTY_RESULT
            err_message = "未能获取 Claude 响应内容。\n\n" + err_message
        if exit_code is not None and exit_code != 0 and success:
            success = False
            if not error_kind:
                error_kind = ErrorKind.SUBPROCESS_ERROR
            err_message = f"进程退出码非零：{exit_code}\n\n" + err_message

        if success:
            break
        else:
            all_last_lines = last_lines.copy()
            last_error = {
                "error_kind": error_kind,
                "err_message": err_message,
                "exit_code": exit_code,
                "json_decode_errors": json_decode_errors,
                "raw_output_lines": raw_output_lines,
            }
            if retries < max_retries:
                retries += 1
                time.sleep(0.5 * (2 ** (retries - 1)))
            else:
                break

    metrics.finish(
        success=success,
        error_kind=error_kind,
        result=result_content,
        exit_code=exit_code,
        raw_output_lines=raw_output_lines,
        json_decode_errors=json_decode_errors,
        retries=retries,
    )
    if log_metrics:
        metrics.log_to_stderr()

    if success:
        result = {
            "success": True,
            "tool": "claude",
            "SESSION_ID": session_id,
            "result": result_content,
            "duration": metrics.format_duration(),
        }
    else:
        if last_error:
            error_kind = last_error["error_kind"]
            err_message = last_error["err_message"]
            exit_code = last_error["exit_code"]
            json_decode_errors = last_error["json_decode_errors"]
        result = {
            "success": False,
            "tool": "claude",
            "error": err_message,
            "error_kind": error_kind,
            "error_detail": _build_error_detail(
                message=err_message.split('\n')[0] if err_message else "未知错误",
                exit_code=exit_code,
                last_lines=all_last_lines,
                json_decode_errors=json_decode_errors,
                idle_timeout_s=timeout if error_kind == ErrorKind.IDLE_TIMEOUT else None,
                max_duration_s=max_duration if error_kind == ErrorKind.TIMEOUT else None,
                retries=retries,
            ),
            "duration": metrics.format_duration(),
        }

    if return_all_messages:
        result["all_messages"] = all_messages
    if return_metrics:
        result["metrics"] = metrics.to_dict()
    return result