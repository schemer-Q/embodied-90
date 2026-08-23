# Week 2 Day 5: Fixed-Seed Full Trajectory

## 配置

- Run ID：`week02_day05_seed0_layout0_full`
- RoboDojo commit：`9226f48ea694b3f53db12d4922e8b1199f8d0891`（dirty，状态已固化到元数据）
- 实验仓库 commit：`3c82b9fa81572db91a3377c581d299c8f78f9b9b`
- Task / environment / action：`deposit_coin` / `arx_x5` / `joint`
- Policy / checkpoint：ACT / `RoboDojo-deposit_coin-arx_x5-joint-0`
- `policy_last.ckpt` SHA256：`dfbc1ddc3e207084fb4d13765281d82792bda52f01d6045b0cdcd239a56012e0`
- `dataset_stats.pkl` SHA256：`4a777e14eebb94f5f8db50ad1e137b2a445b59dfa79d8a87d6a9621a4d04ef5b`
- Seed / layout / environments：`0` / `0` / `1`
- Policy / internal steps：`300` / `10`
- Python / PyTorch / Isaac Sim：`3.11.15` / `2.7.0+cu128` / `5.1.0.0`
- ACT：`temporal_agg=false`，`query_frequency=50`，每个 chunk 逐步消费 50 个 action

完整启动命令、随机性环境变量、主仓库及子模块状态见
[full_episode_metadata.json](week02_day05/full_episode_metadata.json)。本次运行明确移除了
`ACT_DEBUG_STOP_STEP`，未进行人工干预。

## 完整性

| 检查项 | 结果 | 证据 |
|---|---:|---|
| Policy steps | Pass，300/300 | [策略轨迹](week02_day05/full_episode_trace.jsonl) |
| Internal records | Pass，3000/3000 | [内部控制轨迹](week02_day05/full_episode_internal.jsonl) |
| Missing steps | Pass，`[]` | [完整性摘要](week02_day05/full_episode_summary.json) |
| 每步内部序列 | Pass，每步 `1..10` | [完整性摘要](week02_day05/full_episode_summary.json) |
| NaN / Inf | Pass，0 | [完整性摘要](week02_day05/full_episode_summary.json) |
| Action validation | Pass，0 failure | [完整性摘要](week02_day05/full_episode_summary.json) |
| 三路视频 | Pass，各 301 帧，640x480，25 FPS | [视频清单](week02_day05/video_manifest.json) |
| 结果一致性 | Pass，轨迹与 `_result.json` 一致 | [result.json](week02_day05/result.json) |
| Exit code | Pass，0 | [完整日志](week02_day05/full_episode.log) |

策略轨迹另提供便于表格分析的 [CSV](week02_day05/full_episode_trace.csv)。每条 policy
记录包含 ACT action、chunk 编号/索引、实际关节、夹爪、双侧末端位姿、硬币位姿、
reward、score 和 success；内部轨迹另包含插值 target、写入 target 和实际关节位置。

## 关键事件时间线

| Policy step | 事件 | 证据与边界 |
|---:|---|---|
| 1 | 首个 ACT chunk，开始运动 | `act_chunk_number=0`，`act_chunk_index=0` |
| 19 | 左夹爪开始闭合 | 实际主关节低于初值 `0.044 m` 超过 `0.002 m` |
| 25 | 末端 link origin 与硬币最近 | 最近距离 `0.177819 m`；不是指尖距离或物理接触证据 |
| 34 | 左夹爪明显闭合 | 实际主关节首次低于 `0.01 m` |
| 51 | ACT chunk 刷新 | chunk 1 / index 0；随后每 50 步刷新 |
| 151 | 最大瞬时 tracking error | chunk 3 / index 0，最大绝对误差 `0.795768 rad` |
| 251 | 最后一次 ACT chunk 刷新 | chunk 5 / index 0 |
| 300 | Episode 正常结束 | `success=false`，`score=0.0` |

ACT chunk 刷新发生在 policy step `1, 51, 101, 151, 201, 251`。step 151 的新 action
相对上一状态产生较大关节目标跳变；10 个内部控制 target 仍完整写入，实际关节沿相同方向
响应，但未在一个 policy step 内跟上最终 target。因此该峰值是 chunk 边界的瞬时跟踪误差，
不是维度丢失或控制队列中断的证据；其行为风险仍应在后续时序分析中保留。

“末端开始抬升”的自动候选为 step 4，但它只表示左末端 Z 相对此前局部最低点增加超过
`0.005 m`，不能视为抓住硬币后的抬升。硬币在该时刻及此后均未跟随运动。

## 最终结果

- Success：`false`
- Score：`0.0`
- Reward：全程 `0.0`
- 硬币初始 Z：`0.7805473804 m`（env-relative）
- 硬币最大抬升：`1.7881393e-7 m`
- 最大 joint tracking error：`0.7957679 rad`，policy step 151
- 最早确认失败阶段：夹爪闭合后，硬币未超过 `0.08 m` lift 阈值

硬币位置数值始终有限且基本不变。视觉关键帧见
[keyframes](week02_day05/keyframes)，数值曲线见
[trajectory_plot.png](week02_day05/trajectory_plot.png)。关键帧只能支持接近、对准和疑似接触
的视觉判断，不能替代接触传感器证据。

## 视频

三路完整视频保存在 RoboDojo 评测结果目录，路径和 SHA256 已记录在
[video_manifest.json](week02_day05/video_manifest.json)，未重复提交到 Git：

- `cam_head`：301 帧，SHA256 `3c9040cf...e4d9645`
- `cam_left_wrist`：301 帧，SHA256 `a59af673...d29b450`
- `cam_right_wrist`：301 帧，SHA256 `a5b2a0ad...e102cbd`

## 结论

本次固定 seed、layout、checkpoint 和代码状态的评测完整执行 300/300 policy step，
策略、控制、机器人、硬币和评分记录连续，无缺步或无效数值，终态与正式结果文件一致。
该轨迹可以作为后续根因分析的正式基线。

运行再次确认失败发生在夹爪闭合后、硬币 lift 前。轨迹不支持基础执行中断、动作静默
丢失或单纯成功判定漏触发；仍需重点分析策略产生的抓取姿态/时序、chunk 边界目标跳变，
以及抓取时的具体接触动力学。RoboDojo 及 XPolicyLab 工作树为 dirty，复现时必须同时
使用元数据记录的 commit、子模块状态和已归档 patch。

本日未执行第二次同 seed 确定性复查，因此尚不能对 GPU 仿真的重复运行差异作结论。
