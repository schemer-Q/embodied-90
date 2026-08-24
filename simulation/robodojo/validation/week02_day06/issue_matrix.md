# Official Issue Matrix

检索范围：截至 2026-08-24，使用 GitHub API 检查 RoboDojo 和 XPolicyLab 全部公开 Issue，
并对 `deposit_coin`, `arx_x5`, `ACT`, `gripper`, `action chunk`, `temporal_agg`,
`Isaac Sim 5.1`, `collision`, `friction`, `checkpoint`, `dataset_stats` 做适用性判断。

| Issue | 症状/版本 | 匹配度 | 结论 |
|---|---|---|---|
| [RoboDojo #29](https://github.com/RoboDojo-Benchmark/RoboDojo/issues/29) | Isaac Sim 5.1；env0 articulation drive 在 settle 后被错误固化，joint reward 永不通过 | No | 对应 SpringButton、`press_by_number`/`swap_blocks`；Coin 场景没有相关 articulation 或 `reset_drive` |
| [RoboDojo #23](https://github.com/RoboDojo-Benchmark/RoboDojo/issues/23) | Isaac Sim 5.1 + Blackwell R590/R595 在 RTX 启动时崩溃 | No | 本地完整启动并完成 300 步；症状不匹配。Issue 仍确认 5.1 是官方支持版本 |
| [RoboDojo #4](https://github.com/RoboDojo-Benchmark/RoboDojo/issues/4) | 安装后的依赖冲突 | Partial | 本地 `pip check` 仍有 Starlette/WebSockets 两项冲突，但运行链已通过；是复现风险，不解释 coin pose 不动 |
| [RoboDojo #18](https://github.com/RoboDojo-Benchmark/RoboDojo/issues/18) | X-VLA 发布 checkpoint 与训练 config/data/views 不同步 | No direct / relevant precedent | 不是 ACT，但证明仅凭 checkpoint 名称不能推断代码、数据和相机契约一致 |
| [XPolicyLab #97](https://github.com/XPolicyLab/XPolicyLab/issues/97) | Xiaomi adapter 的 action/gripper contract 与官方 checkpoint 不兼容 | No direct / relevant precedent | 不是 ACT；维护者确认 checkpoint-code mismatch 曾真实发生，支持保留 provenance 风险 |

## Search Result

未发现公开 Issue 直接报告以下组合：`deposit_coin + arx_x5 + ACT`、ACT gripper scale、ACT
temporal aggregation/chunk 边界、Coin friction/collision 或本 checkpoint 的
`dataset_stats.pkl`。因此不存在可直接套用的官方 Issue 根因结论。

Issue #18/#97 只能作为“checkpoint contract 必须显式核验”的先例，不能作为本项目发生同类
错误的证据。Issue #29/#23 的版本与部分环境相似，但对象类型或失败症状不同，已排除直接
适用性。
