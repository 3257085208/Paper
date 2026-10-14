# PVE 只读研究遥测

状态：采集中。第一版仅取到两条 PVE API 样本，PVE 宿主 CPU 字段连续为 0，已停止且标记为预探测数据。第二版增加 Linux `/proc/stat` 累计计数和 CPU PSI，以便交叉核对；每 60 秒采样，目标连续 7 天，由本地 Codex 会话运行。当前第二版已有 3 条记录。

## 来源与安全范围

- 来源：用户指定的 OVH PVE 单节点。
- PVE 报告 Intel Xeon E5-1630 v4、4 个物理核和 8 个逻辑 CPU；旧运营表的“8 核”口径待核对。不要把逻辑线程直接当物理核。
- 只读接口：PVE `pvesh get /nodes`、`/nodes/{node}/status` 和 `/cluster/resources --type vm`；Linux `/proc/stat` 及 `/proc/pressure/cpu`。
- 采集内容：UTC 时间、匿名节点/VM ID、节点状态、PVE CPU 原始值、Linux CPU 累计计数及 PSI、内存读数、运行 VM 类型/状态、配置 vCPU 和 CPU/内存读数。
- 匿名化：远端采集进程为每次运行生成随机密钥，仅在内存中对 VM ID 和节点名作 HMAC；不保存密钥与原始名称，不采集 IP、网络流量、磁盘内容或业务请求。
- 生产主机上没有进行压力测试；没有启动、停止、重启、改配 VM，没有安装采集组件。
- 数据写在本地 `pve_metrics_v2.jsonl`，目录与文件仅当前 macOS 用户可读。不要将原始遥测公开或未经脱敏上传。

## 字段

第二版每行是一个 JSON 对象，包含 `timestamp_utc`、`nodes`、`guests`、`host_cpu_counters`、`host_cpu_pressure`、`error`。CPU 字段保留原始口径，不先解释成需求或利用率百分数。VM 记录只包含 HMAC ID、节点 HMAC、类型、状态、vCPU 配置、原始 CPU 值和内存读数。

预探测文件 `pve_metrics.jsonl` 只有两条记录，PVE 宿主 CPU 原始值均为 `0`，只用于标记接口口径问题，不纳入分析。第二版前三点形成两个 63 秒窗口：PVE CPU 原始值仍均为 `0`，而 `/proc/stat` 推算宿主忙碌时间分别约 27.6% 和 28.5%；PSI `some` 增量分别约 4.46 秒和 4.34 秒。这个短窗口只说明 PVE 指标口径需要核验，不能当论文结果。宿主内存读数是单个时刻的 PVE 快照，不能直接当可分配余量。
