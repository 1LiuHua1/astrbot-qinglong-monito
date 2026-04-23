# 青龙面板监控插件 for AstrBot

## 功能
- 查询定时任务、订阅管理、环境变量、依赖管理列表
- 查看任务最新日志
- 立即运行任务
- 监控任务状态变化，失败或完成时主动推送

## 安装步骤
1. 将本插件解压到 AstrBot 的 `plugins/` 目录下，确保 `qinglong_monitor.py` 位于 `plugins/qinglong_monitor/` 中。
2. 安装依赖：`pip install aiohttp`
3. 复制 `config.example.json` 为 `settings.json`，并填写你的青龙面板信息。
   - 配置文件存放路径：`AstrBot/data/plugins/qinglong_monitor/settings.json`
4. 重启 AstrBot 或执行 `reload` 命令。

## 配置说明
| 参数 | 说明 |
|------|------|
| ql_url | 青龙面板访问地址，例如 `http://192.168.1.100:5700` |
| ql_client_id | 青龙面板应用设置中的 Client ID |
| ql_client_secret | 对应的 Client Secret |
| monitor_interval | 监控间隔（秒），默认 60 |
| monitor_task_names | 需要监控的任务名称列表，空则监控所有 |
| notify_on_success | 任务成功完成时是否通知 |
| notify_on_failure | 任务失败/超时时是否通知 |

## 使用命令
- `.ql help` - 显示帮助
- `.ql cron list [关键词]` - 列出定时任务
- `.ql env list [关键词]` - 列出环境变量
- `.ql sub list [关键词]` - 列出订阅管理
- `.ql dep list [关键词]` - 列出依赖管理
- `.ql cron log <任务名/ID>` - 查看任务日志
- `.ql cron run <任务名/ID>` - 立即运行任务
- `.ql monitor on/off` - 开启/关闭状态推送

## 示例
.ql cron list 签到
.ql cron log 京东签到
.ql cron run 京东签到
.ql env list
.ql monitor on

## 常见问题
- **获取 token 失败**：检查 URL、Client ID/Secret 是否正确，青龙面板是否开启 OpenAPI。
- **日志过长**：插件会自动截取末尾 2000 字符。
- **推送不生效**：请先执行 `.ql monitor on` 订阅，并确保配置中 `notify_on_success/failure` 为 true。

## 依赖文件
aiohttp>=3.8.0
