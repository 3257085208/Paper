# 第二台生产宿主（承载客户 VPS）只读遥测

状态：首轮逐 VM 遥测已于 2026-10-11 21:03 至 2026-10-12 00:05（Asia/Shanghai）采集完成，共 **170 个样本**（60 秒间隔，约 3.0 小时，零错误；运行中 VM 197–208 台；宿主忙率均值 29.5%、P95 36.6%；CPU PSI some avg10 均值 7.7、峰值 36.2），样本见 `pve_metrics.jsonl`。采集因远端断开而中止。已准备**超轻模式**采集器（`../../collect_pve_light.py`：5 分钟间隔、仅 `/proc` 与 PSI、零 PVE API、远端零写入、断线自动重连）。2026-10-12 起经跳板机 `117.55.225.227`（`~/.ssh/config` 别名 `nkx-relay` → `hk-vps`，ProxyJump，密钥登录）恢复采集（`screen` 会话 `sci2light`，目标 7 天），样本写入 `pve_host_light.jsonl`。启动快照：运行中 VM 260 台、load ≈52–65 / 50 核、CPU PSI some avg300 ≈15、内存可用 ~11.5 / 271 GB。

## 来源与安全范围

- 来源：用户指定的另一台承载客户业务的宿主机（用户称“另一台 VPS”），经 SSH 端口 2828、专用密钥接入。
- 该机为 KVM 客户机内部的嵌套 PVE（PVE 9.2.21，内核 7.0.14-20-pve，Debian 13）；`systemd-detect-virt` 报告 `kvm`，CPU 虚拟化标志 `vmx` 与 `/dev/kvm` 均可用。节点报告 50 个 CPU（Xeon Gold 6248）、约 252 GiB 内存、1.1 TB 根盘（约 28% 使用）；检查时 206 台配置 VM、198 台运行。
- 只读接口：PVE `pvesh get /nodes`、`/nodes/{node}/status`、`/cluster/resources --type vm`；Linux `/proc/stat` 与 `/proc/pressure/cpu`。
- 匿名化：远端进程每次运行生成随机密钥，仅在内存中对 VM ID 与节点名做 HMAC；不保存密钥与原始名称，不采集 IP、业务内容或磁盘数据。
- 未加压、未启停或修改任何 VM、未安装采集组件。访问使用专用密钥 `~/.ssh/sci2_key`（已加入该机 root 的 `authorized_keys`）。
- 数据写入本地 `pve_metrics.jsonl`；目录与文件仅当前 macOS 用户可读。不要公开原始遥测。

## 字段

与 `../ovh_readonly/README.md` 相同：每行一个 JSON 对象，含 `timestamp_utc`、`nodes`、`guests`、`host_cpu_counters`、`host_cpu_pressure`、`error`。嵌套虚拟化下，物理核数无法在该机内核实，容量分母以节点报告值为准并在分析中注明。

## 2026-10-13 采集恢复记录

- HK 宿主在 10-12 夜间发生主机密钥变化（疑似重装/重建）；旧指纹导致轻量采集器中断在 7 个样本。
- 用户提供新访问路径；确认经原 relay（117.55.225.227）仍可直达 HK 宿主，密码已通过**会话环境变量**使用、
  未写入任何文件；已安装 `sci2_key` 公钥，之后为密钥免密（`~/.ssh/config` 的 `hk-vps` 别名，ProxyJump relay）。
- 用户另提供的新跳板 38.207.172.110:2828 对本机/IPv6 出口在当前网络下不可用（KEX 前断开，疑有来源白名单），
  未采用；备用记录在案。
- 采集器（screen `sci2light`）已自动恢复，新样本持续写入本目录 `pve_host_light.jsonl`。
  注意：前 7 个样本与之后样本属不同宿主实例（重建前/后），分析时按时段分开；主机名仍为 LEC-HK-1，
  当前负载显著高于首轮（PSI some avg10 ≈ 26 vs 首轮 7.7；load ≈ 22–24）——生产画像的"高负载段"样本。

## 2026-10-13 宿主清点

- `host_inventory_20261013.md`：一次性只读清点（`tools/hk_inventory.sh`，经 relay stdin 执行，不调 PVE API、不在远端落盘）：
  Xeon Gold 6248 ×50 核 / 251.7 GiB / 1.1 TB SSD；285 VM 配置（276 运行）；ΣvCPU 417（8.3×）、
  Σ内存 500 GB（2.0×）、Σ磁盘 5.38 TB 薄分配（4.9×，实占 36%）；qcow2 薄克隆 + base 模板共享。
  定位：作者自有宿主，以免费 VPS 开放给外部用户；已写入论文 7.6（中英）与引言。
