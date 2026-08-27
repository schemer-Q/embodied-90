# Week 3 Day 2: Temporal Aggregation A/B Experiment

## 结论

H2 **显著削弱**。`temporal_agg=true` 显著降低了 action jump、jerk、joint tracking error 和末端轨迹突变，但抓取几何明显退化，硬币从可观位移变为几乎不动，最终仍为 `success=false`、`score=0.0`。

因此 chunk 边界跳变是需要修复的工程风险，但不是当前 Coin-X5 取币失败的主要原因。当前证据反而显示，官方聚合模式在本次 seed 0 轨迹中牺牲了抓取对准。

## 配置与单变量

- A：RGB + `temporal_agg=false`。
- B：RGB + `temporal_agg=true`。
- 两组固定 checkpoint、dataset stats、seed 0、layout 0、相机顺序、collision、插值、夹爪尺度、控制频率和 300 policy steps。
- 两组均设置 `ACT_INPUT_COLOR_ORDER=rgb`、`ACT_MAX_TIMESTEPS=300` 和 `ACT_GEOMETRY_MESH_CATEGORIES=vertical_coin_stand,piggy_bank`。
- 唯一自变量为 temporal aggregation 模式及其固有的网络查询频率和候选聚合行为。

精确命令、哈希和版本见 [experiment_config.json](week03_day02_temporal_agg/experiment_config.json) 和各组 `full_episode_metadata.json`。

## 兼容性验证

本地代码原先存在两个 true-only 兼容问题：

1. `all_time_actions` 初始化误缩进到 `ACT_QUERY_FREQ` 分支；
2. ACT 初始化后，`Model.reset()` 再次分配约 `1.32 GiB` buffer，实际 smoke 触发 GPU OOM。

兼容 patch 将初始化放回 `if self.temporal_agg`，支持以 `ACT_MAX_TIMESTEPS=300` 按 episode 容量分配，并让 reset 原地清零已有 buffer。false 的 query frequency、chunk 消费和 action 选择代码均未改变。由于修改了公共代码 revision，正式 A/B 两组均重新运行。

- 语法检查：Pass。
- 确定性公式 smoke：Pass；候选数为 `1,2,...,50,50...`，每步输出有限 14-D action，权重和为 1。
- 实际 Isaac Sim 5-step smoke：Pass；buffer reset 正常，无 OOM、索引错误或 NaN/Inf。
- 兼容 patch：[temporal_agg_compatibility.patch](week03_day02_temporal_agg/temporal_agg_compatibility.patch)。
- Synthetic 证据：[temporal_agg_smoke.json](week03_day02_temporal_agg/temporal_agg_smoke.json)。

## 运行完整性

| 检查项 | False A | True B |
|---|---:|---:|
| Policy server requests | 300 | 300 |
| Network action queries | 6 | 300 |
| Policy steps | 300/300 | 300/300 |
| Internal records | 3000/3000 | 3000/3000 |
| Missing steps | `[]` | `[]` |
| Invalid values | 0 | 0 |
| Videos | 3 路完整 | 3 路完整 |
| Exit code | 0 | 0 |
| Success / score | false / 0.0 | false / 0.0 |

false 每 50 步查询一次并顺序消费 chunk；true 每步查询一次，并聚合最多 50 个覆盖当前时刻的候选。候选达到 50 时，官方 `exp(-0.01 * arange)` 归一化权重从最早候选的 `0.02529` 下降到最新候选的 `0.01549`。完整日程见 [aggregation_schedule.csv](week03_day02_temporal_agg/aggregation_schedule.csv)。

## 平滑性与跟踪

| 指标 | False A | True B | 变化 |
|---|---:|---:|---:|
| Mean adjacent action L2 | 0.1014 | 0.0650 | -35.9% |
| Max adjacent action L2 | 1.6753 | 0.2632 | -84.3% |
| Max single-dimension jump | 0.7750 | 0.1641 | -78.8% |
| Max action jerk L2 | 3.3339 | 0.0845 | -97.5% |
| Mean chunk-boundary jump L2 | 1.0111 | 0.0534 | -94.7% |
| Max chunk-boundary jump L2 | 1.6753 | 0.0734 | -95.6% |
| Max joint tracking error | 0.5916 rad | 0.0382 rad | -93.5% |
| Max left-EE adjacent displacement | 38.29 mm | 25.74 mm | -32.8% |

true 在 step 51/101/151/201/251 的 action jump 均低于 `0.074`，false 在这些边界最高达到 `1.675`。H2 的“chunk 边界不连续”现象因此得到确认并被 aggregation 有效缓解。

## 抓取几何与任务结果

| 指标 | False A | True B | True - False |
|---|---:|---:|---:|
| 夹爪开始闭合 | step 18 | step 19 | +1 |
| 夹爪明显闭合 | step 35 | step 30 | -5 |
| 闭合时 mesh-surface 距离 | 0.015 mm | 15.870 mm | +15.855 mm |
| 闭合时 midpoint 对准误差 | 6.880 mm | 34.939 mm | +28.059 mm |
| 最大硬币位移 | 80.864 mm | 0.001 mm | -80.863 mm |
| 最大硬币抬升 | 10.535 mm | 0.000 mm | -10.535 mm |
| Success / score | false / 0.0 | false / 0.0 | 无改善 |

true 虽然更平滑，但夹爪闭合时离硬币更远，硬币没有产生可观运动。它未满足“平滑性、tracking 和抓取结果同时改善”的 H2 支持条件，符合“平滑但抓取无改善或退化”的显著削弱条件。

## 初始状态与残余风险

- coin 初始位置最大差：`0.0 m`。
- robot 14-D qpos 最大差：`0.0`。
- 三路 reset 图像 shape 和通道配置一致，但两次 Isaac Sim 启动并非逐像素确定；JPEG 帧 MAE 为 `1.53–2.06/255`。
- reset 图像均值接近，差异记录为 renderer/JPEG 非确定性，而不是隐藏配置差异。证据见 [initial_observation_comparison.json](week03_day02_temporal_agg/initial_observation_comparison.json)。
- 本实验只有一组 seed 0 配对；结论针对当前固定配置，不声称 temporal aggregation 在所有 layout 上都会退化抓取。

## 产物

- [False 结果](week03_day02_temporal_agg/false/result.json)
- [True 结果](week03_day02_temporal_agg/true/result.json)
- [False 轨迹摘要](week03_day02_temporal_agg/false/trajectory_summary.json)
- [True 轨迹摘要](week03_day02_temporal_agg/true/trajectory_summary.json)
- [配对摘要](week03_day02_temporal_agg/paired_summary.json)
- [逐步对照](week03_day02_temporal_agg/paired_comparison.csv)
- [平滑性曲线](week03_day02_temporal_agg/action_smoothness_plot.png)
- [闭合关键帧对照](week03_day02_temporal_agg/closure_keyframe_comparison.png)
- [运行脚本](week03_day02_temporal_agg/run_ab_test.sh)

## 下一步

Day 3 继续保持 RGB。使用冻结 scripted/专家轨迹，仅切换 `vertical_coin_stand` collision，验证 H3；不要把 temporal aggregation 或颜色通道变化混入 collision 对照。
