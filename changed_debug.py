"""
MIT License

Copyright (c) 2026 Thierry

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from ansible.plugins.callback import CallbackBase
import json
import os

DOCUMENTATION = r'''
name: changed_debug
type: stdout
short_description: Filtered callback output with debug, changed and recap views
description:
    - Filters task output while keeping debug and changed/not-ok visibility.
options:
    show_unchanged_ok_tasks:
        description:
            - When true, unchanged ok task events are printed.
        type: bool
        default: false
        ini:
            - section: callback_changed_debug
              key: show_unchanged_ok_tasks
        env:
            - name: ANSIBLE_CHANGED_DEBUG_SHOW_OK
'''

try:
    from ansible import constants as C
except Exception:
    C = None

class CallbackModule(CallbackBase):
    """Emit debug/changed/failure-focused playbook output in JSON format."""

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "stdout"
    CALLBACK_NAME = "changed_debug"
    _TRUE_VALUES = {"1", "true", "yes", "on", "y"}
    _FALSE_VALUES = {"0", "false", "no", "off", "n"}

    def __init__(self):
        super().__init__()
        self.show_unchanged_ok_tasks = False
        self._emitted_events = set()
        self._json_opened = False
        self._pending_event_line = None

    def _to_bool(self, value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in self._TRUE_VALUES:
            return True
        if text in self._FALSE_VALUES:
            return False
        return default

    def set_options(self, task_keys=None, var_options=None, direct=None):
        """Load plugin options from Ansible config and environment variables."""
        super().set_options(task_keys=task_keys, var_options=var_options, direct=direct)

        option_value = None
        try:
            option_value = self.get_option("show_unchanged_ok_tasks")
        except Exception:
            option_value = None

        if option_value is None:
            for env_name in ("ANSIBLE_CHANGED_DEBUG_SHOW_OK", "CHANGED_DEBUG_SHOW_OK"):
                option_value = os.getenv(env_name)
                if option_value is not None:
                    break

        self.show_unchanged_ok_tasks = self._to_bool(option_value, default=False)

    def _sanitize(self, value):
        """Convert complex objects into JSON-serializable primitives."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if hasattr(value, "__dict__"):
            try:
                return self._sanitize(vars(value))
            except Exception:
                return str(value)
        if isinstance(value, dict):
            return {str(self._sanitize(k)): self._sanitize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._sanitize(v) for v in value]
        return str(value)

    def _to_output(self, payload, compact=True):
        payload = self._sanitize(payload)
        if compact:
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)

    def _color_value(self, *names):
        if C is None:
            return None
        for name in names:
            value = getattr(C, name, None)
            if value is not None:
                return value
        return None

    def _display_colored(self, msg, *color_names):
        color = self._color_value(*color_names)
        if color is None:
            self._display.display(msg)
            return
        self._display.display(msg, color=color)

    def _open_json_document(self):
        if self._json_opened:
            return
        self._display.display("{")
        self._display.display('  "events": [')
        self._json_opened = True

    def _emit_event(self, payload, *color_names):
        """Queue one event while preserving valid comma-separated JSON output."""
        self._open_json_document()
        compact = payload.get("event") == "task"
        encoded = self._to_output(payload, compact=compact)
        lines = [f"    {line}" for line in encoded.splitlines()]

        if self._pending_event_line is not None:
            pending_lines, pending_colors = self._pending_event_line
            pending_lines = self._append_comma_to_block(pending_lines)
            self._display_block_colored(pending_lines, *pending_colors)

        self._pending_event_line = (lines, color_names)

    def _append_comma_to_block(self, lines):
        if not lines:
            return lines
        updated = list(lines)
        updated[-1] = f"{updated[-1]},"
        return updated

    def _display_block_colored(self, lines, *color_names):
        for line in lines:
            self._display_colored(line, *color_names)

    def _flush_pending_event(self):
        if self._pending_event_line is None:
            return
        pending_lines, pending_colors = self._pending_event_line
        self._display_block_colored(pending_lines, *pending_colors)
        self._pending_event_line = None

    def _task_role_name(self, task):
        if getattr(task, "_role", None):
            try:
                return task._role.get_name()
            except Exception:
                return getattr(task._role, "_role_name", None)
        return None

    def _is_debug_task(self, task):
        return task.action in ("debug", "ansible.builtin.debug")

    def _is_changed(self, result_data):
        if result_data.get("changed", False):
            return True
        results = result_data.get("results")
        return isinstance(results, list) and any(
            isinstance(item, dict) and item.get("changed", False) for item in results
        )

    def _is_item_result(self, result_data):
        return bool(result_data.get("_ansible_item_result", False))

    def _event_key(self, event_name, result):
        host = result._host.get_name()
        task_uuid = getattr(result._task, "_uuid", result._task.get_name())
        return (event_name, host, str(task_uuid))

    def _should_emit_event(self, event_name, result):
        key = self._event_key(event_name, result)
        if key in self._emitted_events:
            return False
        self._emitted_events.add(key)
        return True

    def _task_payload(self, host, task, **extra):
        payload = {
            "host": host,
            "role": self._task_role_name(task),
            "task": task.get_name(),
        }
        payload.update(extra)
        return payload

    def _emit_result_event(self, event_name, result, *color_names):
        if not self._should_emit_event(event_name, result):
            return
        payload = self._task_payload(
            result._host.get_name(),
            result._task,
            event=event_name,
            result=result._result,
        )
        self._emit_event(payload, *color_names)

    def _handle_ok_result(self, result):
        """Handle successful task results (debug, changed, optional unchanged ok)."""
        host = result._host.get_name()
        task = result._task
        data = result._result or {}
        role_name = self._task_role_name(task)
        task_name = task.get_name()

        if self._is_debug_task(task):
            if not self._should_emit_event("debug", result):
                return
            task_payload = {
                "event": "task",
                "host": host,
                "role": role_name,
                "task": task_name,
                "action": task.action,
            }
            self._emit_event(task_payload, "COLOR_TASK", "COLOR_VERBOSE")
            msg = data.get("msg", data)
            payload = {
                "event": "debug",
                "host": host,
                "role": role_name,
                "task": task_name,
                "msg": msg,
            }
            self._emit_event(payload, "COLOR_OK", "COLOR_DEBUG", "COLOR_VERBOSE")
            return

        if self._is_changed(data):
            if not self._should_emit_event("changed", result):
                return
            payload = {
                "event": "changed",
                "host": host,
                "role": role_name,
                "task": task_name,
            }
            self._emit_event(payload, "COLOR_CHANGED")
            return

        if self.show_unchanged_ok_tasks:
            if not self._should_emit_event("ok", result):
                return
            payload = {
                "event": "ok",
                "host": host,
                "role": role_name,
                "task": task_name,
                "changed": False,
            }
            self._emit_event(payload, "COLOR_OK", "COLOR_VERBOSE")

    def _recap_color_names(self, summary):
        if summary.get("unreachable", 0) > 0:
            return ("COLOR_UNREACHABLE", "COLOR_ERROR")
        if summary.get("failed", 0) > 0:
            return ("COLOR_ERROR",)
        if summary.get("changed", 0) > 0:
            return ("COLOR_CHANGED", "COLOR_WARN")
        return ("COLOR_OK", "COLOR_VERBOSE")

    def v2_runner_on_ok(self, result):
        data = result._result or {}
        if self._is_item_result(data):
            return
        self._handle_ok_result(result)

    def v2_runner_item_on_ok(self, result):
        self._handle_ok_result(result)

    def v2_playbook_on_start(self, playbook):
        self._open_json_document()

    def v2_playbook_on_task_start(self, task, is_conditional):
        # Intentionally disabled: task start does not provide a concrete host,
        # and we only want to display host-bound task results.
        return

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._emit_result_event("failed", result, "COLOR_ERROR")

    def v2_runner_on_unreachable(self, result):
        self._emit_result_event("unreachable", result, "COLOR_UNREACHABLE", "COLOR_ERROR")

    def v2_playbook_on_stats(self, stats):
        """Flush events and print a per-host recap at end of playbook."""
        self._open_json_document()
        self._flush_pending_event()
        self._display.display("  ],")
        self._display_colored('  "play_recap": {', "COLOR_TASK", "COLOR_VERBOSE")

        hosts = sorted(stats.processed.keys())
        for index, host in enumerate(hosts):
            s = stats.summarize(host)
            summary = {
                "ok": s.get("ok", 0),
                "changed": s.get("changed", 0),
                "unreachable": s.get("unreachable", 0),
                "failed": s.get("failures", 0),
                "skipped": s.get("skipped", 0),
                "rescued": s.get("rescued", 0),
                "ignored": s.get("ignored", 0),
            }
            suffix = "," if index < (len(hosts) - 1) else ""
            line = f'    {json.dumps(str(host))}: {self._to_output(summary, compact=True)}{suffix}'
            self._display_colored(line, *self._recap_color_names(summary))
        self._display_colored("  }", "COLOR_TASK", "COLOR_VERBOSE")
        self._display.display("}")
