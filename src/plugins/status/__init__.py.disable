import sys
import os

# 1. 获取当前 demo.py 所在的目录
current_dir = os.path.dirname(os.path.abspath(__file__))
# 2. 将该目录加入环境变量，这样 Python 就能直接找到 linuxdo.py
sys.path.append(current_dir)

# 3. 【关键修改】去掉前面的点，改为绝对导入
from linuxdo import LinuxDoStatusClient 
from chmlfrp import Client as ChmlfrpStatusClient

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg

status_command = on_command("状态", aliases={"status"}, priority=5)


def _make_forward_nodes(bot: Bot, chunks: list[str]) -> list[dict]:
    nodes = []
    for chunk in chunks:
        nodes.append(
            {
                "type": "node",
                "data": {
                    "name": "A2Bot",
                    "uin": str(bot.self_id),
                    "content": chunk,
                },
            }
        )
    return nodes


def _format_group_status(group_summary: dict) -> str:
    if not group_summary:
        return "分组汇总：无数据"
    lines = ["分组汇总："]
    for group, stats in group_summary.items():
        parts = [f"total={stats.get('total', 0)}"]
        for key in sorted(k for k in stats.keys() if k != "total"):
            parts.append(f"{key}={stats.get(key, 0)}")
        lines.append(f"- {group}: " + ", ".join(parts))
    return "\n".join(lines)


def _format_models_by_group(title: str, data: dict | list) -> str:
    if not data:
        return f"{title}：无"
    lines = [f"{title}："]
    if isinstance(data, list):
        lines.append("、".join(data))
        return "\n".join(lines)
    for group, models in data.items():
        if not models:
            continue
        lines.append(f"- {group}: " + "、".join(models))
    if len(lines) == 1:
        return f"{title}：无"
    return "\n".join(lines)


def _format_provider_list(title: str, providers: list, limit: int = 10) -> str:
    if not providers:
        return f"{title}：无"
    lines = [f"{title}："]
    for p in providers[:limit]:
        latency = f"{p.latest_latency_ms}ms" if p.latest_latency_ms is not None else "未知"
        ping = f"{p.latest_ping_latency_ms}ms" if p.latest_ping_latency_ms is not None else "未知"
        status = p.latest_status or "unknown"
        msg = f" | {p.latest_message}" if p.latest_message else ""
        lines.append(
            f"- {p.name} ({p.group}/{p.model}) {status} 延迟:{latency} ping:{ping}{msg}"
        )
    return "\n".join(lines)


def _format_chmlfrp_group_stats(nodes: list) -> str:
    if not nodes:
        return "分组汇总：无数据"
    summary: dict[str, dict[str, int]] = {}
    for n in nodes:
        group = n.nodegroup or "unknown"
        summary.setdefault(group, {"total": 0, "online": 0, "offline": 0})
        summary[group]["total"] += 1
        if n.state.lower() == "online":
            summary[group]["online"] += 1
        else:
            summary[group]["offline"] += 1
    lines = ["分组汇总："]
    for group in sorted(summary.keys(), key=lambda x: x.lower()):
        s = summary[group]
        lines.append(f"- {group}: total={s['total']}, online={s['online']}, offline={s['offline']}")
    return "\n".join(lines)


def _format_chmlfrp_nodes(title: str, nodes: list) -> str:
    if not nodes:
        return f"{title}：无"
    lines = [f"{title}："]
    for n in nodes:
        cpu = f"{n.cpu_usage:.1f}%" if n.cpu_usage is not None else "未知"
        bw = f"{n.bandwidth_usage_percent:.1f}%" if n.bandwidth_usage_percent is not None else "未知"
        up = (
            f"{n.current_upload_usage_percent:.1f}%"
            if n.current_upload_usage_percent is not None
            else "未知"
        )
        counts = []
        if n.cur_counts is not None:
            counts.append(f"cur={n.cur_counts}")
        if n.client_counts is not None:
            counts.append(f"client={n.client_counts}")
        if n.tunnel_counts is not None:
            counts.append(f"tunnel={n.tunnel_counts}")
        count_text = f" | {', '.join(counts)}" if counts else ""
        lines.append(
            f"- {n.node_name} ({n.nodegroup}) {n.state} CPU:{cpu} BW:{bw} UP:{up}{count_text}"
        )
    return "\n".join(lines)


@status_command.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    if not args:
        await status_command.finish("请输入要查询的类别名称。\n例如：\n  1. 状态 linuxdo\n  2. 状态 chmlfrp")
    query = args.extract_plain_text().strip().lower()
    if query == "linuxdo":
        c = LinuxDoStatusClient().refreshIfNeeded()
        avg_latency = f"{c.avgLatencyMs}ms" if c.avgLatencyMs is not None else "未知"
        poll_label = c.pollIntervalLabel
        poll_label = poll_label or (f"{c.pollIntervalMs}ms" if c.pollIntervalMs else "未知")
        summary = (
            "LinuxDo 状态概览\n"
            f"总计: {c.total}\n"
            f"在线: {c.operational}, 降级: {c.degraded}, 失败: {c.failed}, 验证失败: {c.validationFailed}, 维护: {c.maintenance}, error: {c.error}\n"
            f"平均延迟: {avg_latency}\n"
            f"生成时间: {c.generatedAtString or '未知'}\n"
            f"刷新间隔: {poll_label}"
        )
        group_summary = _format_group_status(c.getGroupSummary())
        offline_models = _format_models_by_group("离线模型", c.getOfflineModels(by_group=True))
        degraded_models = _format_models_by_group("降级模型", c.getDegradedModels(by_group=True))
        slowest = _format_provider_list("最慢节点(Top5)", c.getSlowestProviders(5), limit=5)
        fastest = _format_provider_list("最快节点(Top5)", c.getFastestProviders(5), limit=5)
        chunks = [summary, group_summary, offline_models, degraded_models, slowest, fastest]
        group_id = getattr(event, "group_id", None)
        if group_id:
            nodes = _make_forward_nodes(bot, chunks)
            await bot.call_api("send_group_forward_msg", group_id=group_id, messages=nodes)
            await status_command.finish("详细状态已发送。")
        else:
            await status_command.finish("\n\n".join(chunks))
    elif query == "chmlfrp":
        c = ChmlfrpStatusClient().refresh()
        summary = (
            "CHMLFRP 状态概览\n"
            f"总计: {c.total}\n"
            f"在线: {c.online}, 离线: {c.offline}\n"
            f"响应: {c.msg or '未知'} (code={c.code}, state={c.state})"
        )
        group_summary = _format_chmlfrp_group_stats(c.nodes())
        all_nodes = _format_chmlfrp_nodes("全部节点", c.nodes())
        chunks = [summary, group_summary, all_nodes]
        group_id = getattr(event, "group_id", None)
        if group_id:
            nodes = _make_forward_nodes(bot, chunks)
            await bot.call_api("send_group_forward_msg", group_id=group_id, messages=nodes)
            await status_command.finish("详细状态已发送。")
        else:
            await status_command.finish("\n\n".join(chunks))
    else:
        await status_command.finish("请输入正确的类别名称。\n例如：\n  1. 状态 linuxdo\n  2. 状态 chmlfrp")
