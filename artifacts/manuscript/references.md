# 参考文献（已核对版 · 2026-10-13）

> 本轮逐条在线核对：作者、题目、会议/期刊、页码与 DOI 以官方信息源（ACM DL / USENIX / IEEE / arXiv / HAL / 官方仓库与文档）为准；
> 仍无法确证的极少数条目保留【待核】。投稿前按目标期刊格式（Springer 数字样式）转换。

1. S. J. Jandaghi, K. Mahdaviani, A. Mirhosseini, S. Elnikety, C. Amza, B. Schroeder. **AUDIBLE: A Convolution-Based Resource Allocator for Oversubscribing Burstable Virtual Machines.** ASPLOS '24, Vol. 3, 14 pages. DOI 10.1145/3620666.3651376.
2. B. Reidys, P. Zardoshti, Í. Goiri, C. Irvene, D. S. Berger, H. Ma, K. Arya, E. Cortez, T. Stark, E. Bak, M. Iyigun, S. Novaković, L. Hsu, K. Trueba, A. Pan, C. Bansal, S. Rajmohan, J. Huang, R. Bianchini. **Coach: Exploiting Temporal Patterns for All-Resource Oversubscription in Cloud Platforms.** ASPLOS '25, Vol. 1, 18 pages. DOI 10.1145/3669940.3707226.
3. B. Wang, G. Zhao, H. Xu, S. Wu, Z. Yu, J. Liu, J. Lu, S. Xu, F. Meng. **Rethinking Cloud Optimization: Volatility-Driven for Better Outcomes**（Hestia 框架；MCV 波动度指标）. SIGCOMM '26, pp. 491–504. DOI 10.1145/3789240.3829141.
4. S. M. Sajal, L. Marshall, B. Li, S. Zhou, A. Pan, K. Mellou, D. Narayanan, T. Zhu, D. Dion, T. Moscibroda, I. Menache. **Kerveros: Efficient and Scalable Cloud Admission Control.** OSDI '23, pp. 227–245, USENIX.
5. L. Wang, M. Das, F. Yang, J. Sheng, B. Qiao, H. Dong, S. Qin, V. Rühle, C. Bansal, E. Cortez, Í. Goiri, S. Rajmohan, Q. Lin, D. Zhang. **Risk-aware Adaptive Virtual CPU Oversubscription in Microsoft Cloud via Prototypical Human-in-the-loop Imitation Learning**（ProtoHAIL）. arXiv:2401.07033, 2024. DOI 10.48550/arXiv.2401.07033.
6. **ORAIL**（ProtoHAIL 后续系列工作）.【待核：正式出处；正文以 [5] 为主引用】
7. P. Jacquet, T. Ledoux, R. Rouvoy. **SCROOGEVM: Boosting Cloud Resource Utilization With Dynamic Oversubscription.** IEEE Trans. Sustainable Computing 9(5):754–765, 2024.
8. **面向 GPU 集群的共形需求包络**（以共形预测构建可校准的超售风险包络，2024/2025）.【待核：正式出处】
9. M. Majd, F. Cheng, A. Pahlevan. **Right-sizing Recommendations (RSR): Cloud Workload Conformal Prediction for Virtual Machines in Data Center Operations.** WI-IAT 2025（作者承稿）；arXiv:2607.24773.
10. S. He, T. Liu, P. Lama, J. Lee, I. K. Kim, W. Wang. **Performance Testing for Cloud Computing with Dependent Data Bootstrapping**（Metior 方法论）. ASE 2021, pp. 666–678, IEEE.
11. InditexTech. **k8s-overcommit-operator**（Kubernetes 超售类别运算符，Apache-2.0，v1.3.4）. https://github.com/InditexTech/k8s-overcommit-operator
12. Red Hat. **ClusterResourceOverride**（OpenShift Container Platform 准入插件，按 request/limit 比例控制节点密度）. https://docs.openshift.com/ 【待核：直达页】
13. KubeVirt. **Per-VM CPU Overcommitment Configuration in KubeVirt**（issue #15710；2025-09 提出，2026-02 关闭——每 VM 自定义超售比尚未支持）；全局 `cpuAllocationRatio` 配置文档. https://github.com/kubevirt/kubevirt/issues/15710
14. P. Jacquet, T. Ledoux, R. Rouvoy. **SweetSpotVM: Oversubscribing CPU without Sacrificing VM Performance.** CCGrid 2024, pp. 148–157, IEEE；以及 **SlackVM: Packing Virtual Machines in Oversubscribed Cloud Infrastructures.** HAL hal-04636648 / IEEE Xplore 10740881.【SlackVM 作者列表待核】
15. Calabi（工程文档）. **Host Resource Management / Host Memory Oversubscription**（Gold/Silver/Bronze 分层 slice、zram/KSM/THP 组合、CPU 超售 1.72:1 实锚）. https://gprocunier.github.io/calabi/
16. Linux kernel documentation. **Control Group v2.** https://docs.kernel.org/admin-guide/cgroup-v2.html
17. Linux kernel documentation. **Pressure Stall Information (PSI).** https://docs.kernel.org/accounting/psi.html
18. Linux kernel documentation. **cgroup v2 IO controller**（`io.max` / `io.weight` / `io.cost` / `io.latency`；见 [16] 的 IO 章节）. https://docs.kernel.org/admin-guide/cgroup-v2.html#io
19. **KVM 超售调度**：KVM Forum 2021（锁持有者抢占与 vCPU 自旋）；LKML 2025-12 系列 "sched/kvm: Semantics-aware vCPU scheduling for oversubscribed KVM"（vCPU debooster、IPI-aware directed yield）.【待核：邮件列表链接与合入状态】
20. Proxmox Server Solutions. **Proxmox VE 文档**（QEMU/KVM 配置与外部指标服务器接口）. https://pve.proxmox.com/pve-docs/
21. QEMU Project. **Virtio-Balloon Free Page Reporting.** https://wiki.qemu.org/Features/FreePageReporting（抓取时受反爬保护，链接为官方 wiki 页）
22. Linux kernel documentation. **Kernel Samepage Merging (KSM)** https://docs.kernel.org/admin-guide/mm/ksm.html ；**zram: Compressed RAM-based block devices** https://docs.kernel.org/admin-guide/blockdev/zram.html
23. S. Lambert, E. Caron, L. Lefèvre, R. Grivel. **Consolidation of virtual machines to reduce energy consumption of data centers by using ballooning, sharing and swapping mechanisms**（ORCA）. Future Generation Computer Systems 174:107968, 2026. DOI 10.1016/j.future.2025.107968.
