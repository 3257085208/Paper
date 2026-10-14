# KVM/云超售现有解决方案盘点（GitHub/文献扫描 · 2026-10-13）

> 目的：为论文的创新点定位找参照——现有工作解决了什么、假设了什么、在"小型 VPS 服务商"场景下缺什么。
> 扫描范围：AUDIBLE/Couch/Hestia/SCROOGEVM 系列论文 + GitHub 开源实现 + Proxmox/Volcano 等工程实践。

## 1. 学术方案

| 方案 | 机制 | 关键假设 | 对我们的缺口 |
|---|---|---|---|
| **AUDIBLE**（ASPLOS'24，微软） | 卷积式计算风险：服务器 24h 用量经验分布 × 新 VM 保守 PMF（同配置 95 分位），卷积估计超容概率 | **假设各 VM 需求相互独立**；用量=需求 | ① 同步相位下独立性失效（我们物理机实验：同步安全容量仅为随机的 1/5）；② 配额截断时用量 ≠ 需求（我们用 1.5 核 vs 真值 5 核证实） |
| **Hestia**（SIGCOMM'26） | 波动度量 MCV + 按周期互补性聚合负载，聚合体为超售单位；MCV 降 43.3%、利润 +66.7% | **可控制放置**（先聚合再超售）；周期性可从历史外推 | ① 我们场景客户"自带相位、随意到达"，无法选择聚合对象；② 同步突发恰是"互补性聚合"的反面（把所有峰值叠在一起），Hestia 分类器会把同步负载排除在可聚合池外——但不解决它们如何被安全接纳 |
| **Coach**（ASPLOS'25，微软） | 全资源超售：长期预测 + 互补调度 + CoachVM（保底+超售两部分资源） | VM 级时间模式可预测；可控制共置 | 同上（放置可控假设）；且聚焦大云的多资源，不涉及配额截断 |
| **SCROOGEVM**（Jacquet et al.） | 动态超售比：侦探 PM 稳定性（LSTM 预测 vs 历史），稳定就逐步提高比例 | 用量=需求；比例可动态调 | 不涉及相位/截断；调整的是"比例"而非"准入决策" |
| **SweetSpotVM / SlackVM**（同组） | 多级超售模板（1.0/1.5/2.6）分配到不同 VM；本地调度器绑定核 | 请求方声明超售档位 | 模板静态，不测量相位与截断 |

## 2. 开源工具与实践

| 项目 | 做什么 | 缺什么 |
|---|---|---|
| **oVirt MOM** | 策略驱动的内存超售（ballooning/KSM），架构可扩展 | 内存域为主；CPU 需求估计无；无相位感知 |
| **kvmtop**（cha87de） | KVM 监控工具，明确指出"VM 内外利用率差异"（超配时内外不一致） | 只是监控，非准入决策 |
| **inspektor-gadget `top_cpu_throttle`** | 读 `cpu.stat` 的 `nr_throttled/throttled_usec`，报告容器节流程度 | **离我们最近的工具**：拿节流计数做"诊断"，但不做需求恢复、不接准入 |
| **Proxmox 官方**（cpulimit/cpuunits/affinity） | 工程原语：硬限速、权重、绑核 | 文档明确"无自动准入"；权重"不护尾"我们已将其证伪（第 4.4.2 节） |
| **Volcano 共置**（k8s） | CPU burst + 动态超售：按节点实时利用率算可超售资源；80% 水位驱逐离线负载 | **纯 reactive**：只有"实时用量+水位"，同步突发瞬间会先越线再驱逐；不识别相位、不校正截断 |
| **CloudVAMP** | ballooning + 实时迁移防内存过载 | 内存域、reactive |

## 3. 结论：三个无人占据的交叉点（我们的定位）

```
       配额截断（censoring）          相位结构（synchronization）
AUDIBLE ✗ 用量当需求                ✗ 假设独立 → 同步时低估风险
Hestia  ✗ 不涉及                    △ 互补聚合为正收益，不解决"同步客户如何安全接纳"
Coach   ✗ 不涉及                    △ 同上
SCROOGEVM ✗ 不涉及                  ✗ 不涉及
工程工具 ✗ 只诊断不恢复              ✗ 只 reactive

我们的方法：
  ① 用节流计数恢复被截断的真实需求（经验估计器 + 声明的适用边界）
  ② 按实测相位结构（时间对齐历史）计容量：随机相位可卖 5×，同步只卖 1×
  ③ 两者的交集：配额 + 同步 + 短历史同时存在时的准入（小服务商的实际场景）
```

**可以直接写进论文 Related Work 的一句话定位**：
"Existing oversubscription systems assume either independence of VM demands (AUDIBLE) or
controllable workload aggregation/placement (Hestia, Coach), and estimate demand from
observed usage. In the small-provider setting, tenants arrive with arbitrary phases, quotas
censor usage, and histories are short. We show (physically) that the same average load yields
5× different safe capacity depending on phase structure, and that quota censoring understates
demand by up to 3.3×—neither is addressed by prior admission systems."

## 4. 可执行的下一步（公平对比实验的设计依据）

用物理机采集的同一份数据，离线复现以下基线的"准入决策"并对比：
1. **固定比例**（1.5×/2×）——实践中位数做法
2. **平均利用率 80% 水位**（Volcano 风格）
3. **历史分位数**（每 VM P95/P99 用量求和；SCROOGEVM 风格）
4. **AUDIBLE 卷积**（用观测用量分布做独立卷积，q99 和 ≤ 容量）——重点：在同步相位下它会高估安全容量（独立性偏差），在截断场景下用错需求值
5. **我们的方法**：截断校正需求 + 时间对齐容量
评价指标：同一 QoS 约束（服务 P99≤10ms 且客户速率 p5≥90% 基准）下"能卖多少台"，以及违约率。

数据资产：`research_data/phys8269_pilot/sell_sell_{rand,sync}*.jsonl`（3 轮 × 每档 60s 逐客户速率）
+ `sweep_*`（膝点）+ `qc_sync_*`（相位）——足够离线复现全部基线。
