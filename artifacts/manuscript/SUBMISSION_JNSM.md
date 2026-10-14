# JNSM 投稿骨架（数据到齐后 2 天填数版）

## 1. 目标与定位
- 期刊：**Journal of Network and Systems Management**（single-blind；先完整性检查）
- 定位一句话：把"安全超售"从阈值问题重写为**观测必要性 + 最小充分观测集**问题，并在双测试床 + 生产遥测上端到端验证。
- 主贡献排序：① 三个不可能性（A/B1/B2/C，两个可证定理构造）+ 最小充分观测集；② PPC 与密度模型；③ 风险校准准入（14 局对决）；④ 无回归资源效率账本。

## 2. 标题/摘要（终稿草稿，EN，待数字回填）
- 标题：*Observation Necessity for Safe Oversubscription: Censoring, Phase Structure and Time Resolution on Small VPS Hosts*（备选沿用现题）
- 摘要要素（~200 词）：三不可能性一句话各证 × 实测数字；最小充分观测集；14 局对决结论（唯一双相位安全 + 40 台崩至 P5 16%）；KSM 33.4% / 微周期 +35%；双床 + 生产遥测 + 可执行反例工件。
- Keywords（5-6）：oversubscription; admission control; censored demand; phase structure; tail latency; observation design。

## 3. Highlights（5 条，≤85 字符/条）
1. Three impossibility results: marginals/utilization/sampling cannot decide safe capacity.
2. Minimal sufficient observation set: censoring evidence + phase profiles + 1-s time resolution.
3. 14-round showdown: only the phase-aware policy is safe in both phases; baselines sell 40 and collapse P5 to 16%.
4. C5 intervention: phase arrangement alone changes capacity x2/x4 (same tenants, same duty).
5. Balloon-free reclaim: 33.4% of fleet RAM, invisible to tenants; micro-period quotas +35% throughput.

## 4. 结构与图表冻结
| 章 | 来源文件 | 状态 |
|---|---|---|
| 1 引言（含速览表） | 01 | ✅ |
| 2 相关工作 | 02 | ✅ |
| 3 模型（3.3.1 + 3.6 + 附录A） | 03 + 附录A | ✅（3.6 措辞待抗混叠直接实验） |
| 4 测量 | 04 | ✅ |
| 5 设计 | 05 | ✅ |
| 6 实现 | 06 | ✅ |
| 7 评估（7.4b 对决） | 07 | ✅（sync 客户 P5 已入库：N=8≈99%、N=16=48.6%） |
| 8 物理机（容量/PPC） | 08 | ⏳ 反相/细扫/回放回填 |
| 9 资源效率 | 09 | ⏳ zram/ioctl/tomo 回填 |
| 10 讨论 / 11 结论 | 10/11 | ✅ |

图（18 张）：fig2-21、27、28 + 待产 fig22-26（Phase C）、fig29（回放）；表：T1 测试床 / T2 负载 / T3 控制矩阵 / T4 生产宿主 / T5 塑形手册 / T6 相关工作矩阵（均已有草稿）。
**口径附录**：统一安全定义（§8.4）、认证协议（§5.3.2）、不可能性（附录 A）——投稿包必备。

## 5. Data Availability Statement（草稿）
All code, raw traces, and analysis scripts are available at github.com/3257085208/Paper (site) and the archived artifact bundle; production telemetry is anonymized (HMAC'd IDs), read-only, collected on infrastructure we operate, and released only in aggregate form. No training/feedback into production.

## 6. 数据依赖清单（投稿前的"待补"开关）
- [x] show5：sync 客户 P5 列（7 局）→ N=8≈99%、N=10=62.2%（首失败）、N=16=48.6%
- [ ] 抗混叠直接对照（变采样间隔）
- [x] boundary 细扫 → 边界收紧：sync [8,10)、rand [28,32)、mix25 [24,28)
- [x] capmix 重复轮（3 轮合并，边界收紧 f25 [24,28)）
- [x] BeroHost v3 返工（膝点 50 轮图 29 / censoring 90 cycle / 三风暴 26 轮，全部回填 §4/§7）
- [x] 生产回放（分钟粒度模型验证）→ 峰值饱和、服务平
- [x] Phase C（zram3b 吸收 176.8GB / ioctl2 / FPR / canary3 全部完成）
- [x] 自查更正：qp2c "+35%" 撤回（qp2v1 干净复测：2ms ≡ 1s，各 0.5 核）；命题 A 措辞精确化
- [x] 容量—风险曲线（图 30，工作负载侧；算法侧前沿列为未来工作）
- [x] A.2/A.3 数学修正（界方向 + 多周期窗 U(L)；T-B4 数值证伪旧式）+ 英文附录 A
- [x] 复现仓库发布（artifacts/tools + research_data + REPRODUCE.md，站点 200）
- [x] 轮级范围/批次对比报告 + 图表重生成（fig16/17/19/21/28/29 + fig22–26 新建）+ 中英同步（形式化 bootstrap CI 待数据冻结终刷）

## 7. Cover Letter（草稿 · 投稿时定稿）

Dear Editor-in-Chief,

We submit for consideration in the *Journal of Network and Systems Management* the manuscript
"Observation Necessity for Safe Oversubscription: Censoring, Phase Structure and Time Resolution on
Small VPS Hosts" by Kaixiang Nie.

Small VPS providers oversubscribe by necessity: many cheap, mostly-idle tenants on a few physical
cores. Yet the prevailing capacity practices — usage panels, average-utilization thresholds,
independence-based convolutions — silently fail in this regime for three structural reasons that
large-cloud research does not face: quotas censor demand, tenant bursts share phase structure, and
short histories force sampling decisions. The manuscript turns these three failure modes into an
organizing principle (observation necessity), backs each with constructive counterexamples (with
executable checks), and delivers the controller that follows from them: a minimal observation set
(censoring evidence + joint phase profiles + one-second resolution) realized as a risk-calibrated
admission controller.

The evidence is unusually direct for this problem class: two self-built testbeds (a 4-vCPU nested
host and a 96-thread bare-metal host with a 64-VM fleet), a complete seven-policy, fourteen-round
admission showdown under identical arrival streams, a phase-arrangement intervention that changes
sellable capacity 2–4x with identical tenants, and read-only telemetry from two production hosts we
operate (285 VMs configured; 8.3x vCPU oversubscription). Every claim carries round-level statistics
and explicit boundary statements, and all code, schedules and raw traces are released for
reproduction.

We believe the work fits the journal's scope at the intersection of measurement-driven systems
research and network/service management: it offers actionable, validated design rules for the
underserved small-host segment and connects to JNSM's ongoing conversation on resource management
for virtualized and cloud infrastructure.

The manuscript is original, has not been published elsewhere, and is not under consideration by
another journal. The author declares no competing interests. All production telemetry was collected
read-only on infrastructure we operate, anonymized, and is released only in aggregate form; no
user-identifying data is included. [Suggested reviewers to be added at submission.]

Thank you for your consideration.

Sincerely,
Kaixiang Nie
Fujian Chuanzheng Communications College
