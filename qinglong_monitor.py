# qinglong_monitor.py
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp

# 兼容不同版本的导入
try:
    from astrbot.api.plugin import BasePlugin, on_command
    from astrbot.api.message import MessageEvent
except ImportError:
    try:
        from astrbot.core.plugin import BasePlugin, on_command
        from astrbot.core.message import MessageEvent
    except ImportError:
        try:
            from astrbot.plugin import BasePlugin, on_command
            from astrbot.message import MessageEvent
        except ImportError:
            raise ImportError("无法找到 AstrBot 的插件基类，请检查安装或联系插件作者。")

logger = logging.getLogger(__name__)

class QinglongMonitorPlugin(BasePlugin):
    # ... 其余所有代码与原插件完全一致，不需要改动 ...
    """
    青龙面板监控插件（兼容 AstrBot v4.23.3）
    """

    def __init__(self):
        super().__init__()
        self.config = {}
        self.session: Optional[aiohttp.ClientSession] = None
        self.token: Optional[str] = None
        self.token_expire_at: float = 0
        self.last_task_status: Dict[str, str] = {}
        self.subscribers: List[MessageEvent] = []

    async def initialize(self) -> None:
        """加载配置并初始化"""
        self.config = self.get_plugin_config()
        required = ["ql_url", "ql_client_id", "ql_client_secret"]
        missing = [k for k in required if not self.config.get(k)]
        if missing:
            logger.error(f"青龙插件缺少配置: {missing}")
            return
        self.config.setdefault("monitor_interval", 60)
        self.config.setdefault("monitor_task_names", [])
        self.config.setdefault("notify_on_success", False)
        self.config.setdefault("notify_on_failure", True)

        self.session = aiohttp.ClientSession()
        asyncio.create_task(self._background_monitor())
        logger.info("青龙面板监控插件初始化成功")

    async def cleanup(self):
        if self.session:
            await self.session.close()
        logger.info("青龙插件已关闭")

    # ------------------- 青龙 API 封装 -------------------
    async def _get_token(self) -> Optional[str]:
        if self.token and time.time() < self.token_expire_at:
            return self.token
        url = f"{self.config['ql_url']}/open/auth/token"
        data = {
            "client_id": self.config["ql_client_id"],
            "client_secret": self.config["ql_client_secret"]
        }
        try:
            async with self.session.post(url, json=data, timeout=10) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    self.token = result.get("data", {}).get("token")
                    expire_in = result.get("data", {}).get("expire_in", 7200)
                    self.token_expire_at = time.time() + expire_in - 60
                    return self.token
                else:
                    logger.error(f"获取token失败: {resp.status}")
                    return None
        except Exception:
            logger.exception("请求token异常")
            return None

    async def _ql_request(self, method: str, path: str, **kwargs) -> Optional[Dict]:
        token = await self._get_token()
        if not token:
            return None
        url = f"{self.config['ql_url']}/open{path}"
        headers = {"Authorization": f"Bearer {token}"}
        async with self.session.request(method, url, headers=headers, **kwargs) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("code") == 200:
                    return data.get("data")
                else:
                    logger.warning(f"API返回错误: {data}")
                    return None
            else:
                logger.error(f"API请求失败: {resp.status}")
                return None

    # ---------- 各资源API ----------
    async def get_crons(self, search: str = None) -> List[Dict]:
        params = {"searchValue": search} if search else {}
        return await self._ql_request("GET", "/crons", params=params) or []

    async def get_cron_log(self, cron_id: int) -> Optional[str]:
        data = await self._ql_request("GET", f"/crons/{cron_id}/log")
        return data.get("log") if data else None

    async def run_cron(self, cron_id: int) -> bool:
        data = await self._ql_request("PUT", "/crons/run", json=[cron_id])
        return data is not None

    async def get_envs(self, search: str = None) -> List[Dict]:
        params = {"searchValue": search} if search else {}
        return await self._ql_request("GET", "/envs", params=params) or []

    async def get_subscriptions(self, search: str = None) -> List[Dict]:
        params = {"searchValue": search} if search else {}
        return await self._ql_request("GET", "/subscriptions", params=params) or []

    async def get_dependencies(self, search: str = None) -> List[Dict]:
        params = {"searchValue": search} if search else {}
        return await self._ql_request("GET", "/dependencies", params=params) or []

    # ---------- 监控逻辑 ----------
    async def _background_monitor(self):
        if not self.config.get("monitor_interval"):
            return
        await asyncio.sleep(10)
        while True:
            try:
                await self._check_task_status_changes()
            except Exception:
                logger.exception("监控异常")
            await asyncio.sleep(self.config["monitor_interval"])

    async def _check_task_status_changes(self):
        tasks = await self.get_crons()
        if not tasks:
            return
        monitor_names = self.config["monitor_task_names"]
        status_map = {0: "空闲", 1: "运行中", 2: "失败", 3: "超时"}
        for task in tasks:
            name = task.get("name", "")
            if monitor_names and name not in monitor_names:
                continue
            cron_id = task.get("id")
            status = status_map.get(task.get("status"), "未知")
            last = self.last_task_status.get(str(cron_id))
            if last is None:
                self.last_task_status[str(cron_id)] = status
                continue
            if last != status:
                need_notify = (status == "失败" and self.config["notify_on_failure"]) or \
                              (status == "空闲" and last == "运行中" and self.config["notify_on_success"])
                if need_notify:
                    log = await self.get_cron_log(cron_id)
                    log_preview = (log[-200:] if log and len(log) > 200 else log) or "无日志"
                    msg = (f"📢 青龙任务状态变化\n"
                           f"任务：{name}\n"
                           f"状态：{last} → {status}\n"
                           f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                           f"日志摘要：\n```\n{log_preview}\n```")
                    for sub in self.subscribers[:]:
                        await self.send_message(sub, msg)
                self.last_task_status[str(cron_id)] = status

    # ---------- 命令处理 ----------
    @on_command("ql")
    async def handle_ql_command(self, event: MessageEvent, args: str):
        if not args:
            await self.send_message(event, await self.get_help())
            return

        parts = args.strip().split()
        cmd = parts[0].lower()

        if cmd == "help":
            await self.send_message(event, await self.get_help())
            return

        sub_cmd = parts[1].lower() if len(parts) > 1 else ""
        keyword = " ".join(parts[2:]) if len(parts) > 2 else ""

        if cmd == "list":
            await self._cmd_list_crons(event, keyword)
            return

        if sub_cmd == "list":
            if cmd in ("cron", "crons"):
                await self._cmd_list_crons(event, keyword)
            elif cmd in ("env", "envs"):
                await self._cmd_list_envs(event, keyword)
            elif cmd in ("sub", "subscription", "subscriptions"):
                await self._cmd_list_subs(event, keyword)
            elif cmd in ("dep", "deps", "dependency"):
                await self._cmd_list_deps(event, keyword)
            else:
                await self.send_message(event, f"未知资源类型：{cmd}，支持：cron, env, sub, dep")
        elif sub_cmd == "log":
            if cmd in ("cron", "crons"):
                await self._cmd_log(event, keyword)
            else:
                await self.send_message(event, "目前仅支持查看定时任务的日志：.ql cron log <任务名/ID>")
        elif sub_cmd == "run":
            if cmd in ("cron", "crons"):
                await self._cmd_run(event, keyword)
            else:
                await self.send_message(event, "目前仅支持运行定时任务：.ql cron run <任务名/ID>")
        elif sub_cmd == "monitor":
            await self._cmd_monitor(event, keyword)
        else:
            await self.send_message(event, await self.get_help())

    async def _cmd_list_crons(self, event: MessageEvent, search: str):
        tasks = await self.get_crons(search)
        if not tasks:
            await self.send_message(event, "❌ 未获取到定时任务，请检查配置或青龙服务。")
            return
        status_map = {0: "✅ 空闲", 1: "🔁 运行中", 2: "❌ 失败", 3: "⏰ 超时"}
        lines = ["📋 定时任务列表："]
        for t in tasks:
            name = t.get("name", "未知")
            status = status_map.get(t.get("status"), "❓")
            schedule = t.get("schedule", "未设置")
            lines.append(f"• {name} [{status}] | {schedule}")
            if len(lines) > 30:
                lines.append("... 输出截断，请使用更精确的搜索词")
                break
        await self.send_message(event, "\n".join(lines))

    async def _cmd_list_envs(self, event: MessageEvent, search: str):
        envs = await self.get_envs(search)
        if not envs:
            await self.send_message(event, "未获取到环境变量。")
            return
        lines = ["🌿 环境变量列表："]
        for e in envs:
            name = e.get("name", "unknown")
            value = e.get("value", "")
            display = value[:50] + ("..." if len(value) > 50 else "")
            lines.append(f"• {name} = {display}")
        await self.send_message(event, "\n".join(lines[:20]))

    async def _cmd_list_subs(self, event: MessageEvent, search: str):
        subs = await self.get_subscriptions(search)
        if not subs:
            await self.send_message(event, "未获取到订阅列表。")
            return
        lines = ["📡 订阅管理列表："]
        for s in subs:
            name = s.get("name", "未知")
            type_ = s.get("type", "")
            status = "✅ 正常" if s.get("status") == 1 else "❌ 异常"
            lines.append(f"• {name} [{type_}] {status}")
        await self.send_message(event, "\n".join(lines[:20]))

    async def _cmd_list_deps(self, event: MessageEvent, search: str):
        deps = await self.get_dependencies(search)
        if not deps:
            await self.send_message(event, "未获取到依赖列表。")
            return
        lines = ["📦 依赖管理列表："]
        for d in deps:
            name = d.get("name", "未知")
            type_ = d.get("type", "nodejs")
            version = d.get("version", "未知版本")
            lines.append(f"• {name} [{type_}] {version}")
        await self.send_message(event, "\n".join(lines[:20]))

    async def _cmd_log(self, event: MessageEvent, arg: str):
        if not arg:
            await self.send_message(event, "请提供任务名称或ID，例如：.ql cron log 签到")
            return
        tasks = await self.get_crons()
        if not tasks:
            await self.send_message(event, "无法获取任务列表")
            return
        target = None
        if arg.isdigit():
            for t in tasks:
                if str(t.get("id")) == arg:
                    target = t
                    break
        if not target:
            for t in tasks:
                if arg.lower() in t.get("name", "").lower():
                    target = t
                    break
        if not target:
            await self.send_message(event, f"未找到任务：{arg}")
            return
        log = await self.get_cron_log(target["id"])
        if log is None:
            await self.send_message(event, f"获取日志失败，任务：{target['name']}")
            return
        if len(log) > 2000:
            log = log[-2000:] + "\n... (日志过长，仅显示末尾)"
        await self.send_message(event, f"📄 任务【{target['name']}】最新日志：\n```\n{log}\n```")

    async def _cmd_run(self, event: MessageEvent, arg: str):
        if not arg:
            await self.send_message(event, "请提供任务名称或ID，例如：.ql cron run 签到")
            return
        tasks = await self.get_crons()
        if not tasks:
            await self.send_message(event, "无法获取任务列表")
            return
        target = None
        if arg.isdigit():
            for t in tasks:
                if str(t.get("id")) == arg:
                    target = t
                    break
        if not target:
            for t in tasks:
                if arg.lower() in t.get("name", "").lower():
                    target = t
                    break
        if not target:
            await self.send_message(event, f"未找到任务：{arg}")
            return
        ok = await self.run_cron(target["id"])
        if ok:
            await self.send_message(event, f"✅ 已触发运行任务：【{target['name']}】")
        else:
            await self.send_message(event, "❌ 触发运行失败")

    async def _cmd_monitor(self, event: MessageEvent, arg: str):
        if arg == "on":
            if event not in self.subscribers:
                self.subscribers.append(event)
                await self.send_message(event, "✅ 已开启定时任务状态推送（任务失败或完成时通知）")
            else:
                await self.send_message(event, "推送已开启")
        elif arg == "off":
            if event in self.subscribers:
                self.subscribers.remove(event)
                await self.send_message(event, "✅ 已关闭推送")
            else:
                await self.send_message(event, "未开启推送")
        else:
            await self.send_message(event, "用法：.ql monitor on  或  .ql monitor off")

    async def get_help(self) -> str:
        return (
            "🔧 青龙面板监控插件\n"
            "命令格式：\n"
            "  .ql help                     - 显示本帮助\n"
            "  .ql cron list [关键词]       - 列出定时任务\n"
            "  .ql env list [关键词]        - 列出环境变量\n"
            "  .ql sub list [关键词]        - 列出订阅管理\n"
            "  .ql dep list [关键词]        - 列出依赖管理\n"
            "  .ql cron log <任务名/ID>     - 查看任务最新日志\n"
            "  .ql cron run <任务名/ID>     - 立即运行任务\n"
            "  .ql monitor on/off           - 开启/关闭任务状态自动推送\n"
            "示例：\n"
            "  .ql env list\n"
            "  .ql sub list\n"
            "  .ql dep list python\n"
            "  .ql cron list 签到\n"
            "  .ql cron log 京东签到\n"
            "  .ql cron run 京东签到"
        )