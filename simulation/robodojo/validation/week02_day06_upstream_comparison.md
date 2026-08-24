# Week 2 Day 6: Upstream and Version Comparison

## 比较基线

- A, current worktree：RoboDojo `9226f48` + dirty main files + dirty/moved submodules
- B, local base commit：`9226f48ea694b3f53db12d4922e8b1199f8d0891`
- C, official upstream main：`2184bf8844ea9d205382c4aefa3a694311418251`（2026-08-20）
- Official XPolicyLab：RoboDojo pin `432f82b`；独立仓库 main `c07a096`
- Checkpoint：`RoboDojo-deposit_coin-arx_x5-joint-0/policy_last.ckpt`
- Checkpoint SHA256：`dfbc1ddc3e207084fb4d13765281d82792bda52f01d6045b0cdcd239a56012e0`
- Dataset stats SHA256：`4a777e14eebb94f5f8db50ad1e137b2a445b59dfa79d8a87d6a9621a4d04ef5b`

本次只执行了 status/diff、依赖查询、GitHub API 检索和 `git fetch` 更新 remote-tracking
refs；没有 checkout、reset、merge、依赖升级或运行参数修改。原始快照见
[local_diff_stat.txt](week02_day06/local_diff_stat.txt)、
[submodule_status.txt](week02_day06/submodule_status.txt) 和
[local_behavior_diff.patch](week02_day06/local_behavior_diff.patch)。

## 本地修改分类

| 文件/组件 | 分类 | 默认是否改变 Day 5 行为 | 与失败相关性 |
|---|---|---:|---|
| `reward_manager/func_parser.py` | Instrumentation | 否 | Low；只拆出等价布尔值并按 `ACT_REWARD_DEBUG` 打印 |
| `robot_manager/control_manager.py` | Behavior-changing, conditional | 否 | Low for Day 5；`GRIPPER_EPS` 未设置，默认仍为 0.2；多余 `pass` 无语义 |
| `objects/geometry.py` | Behavior-changing | **是** | **High**；默认将 stand 和 piggy bank 改为 triangle-mesh collision |
| `objects/rigid.py` | Behavior-changing, conditional | 否 | Low difference；Coin friction env overrides 未设置，仍使用官方 0.6/1.5 |
| `scripts/eval_policy.sh` | Compatibility | 否 | Low；默认仍 headless，只增加 opt-out |
| `src/eval_client/eval_env.py` | Mixed | 部分 | Medium；layout 0 限制在 Day 5 生效但符合固定 layout；其余 replay/direct/no-interp/min-gripper/stop 均未启用，日志和视频开关不改控制语义 |
| `XPolicyLab/ACT/deploy.yml` | Behavior-changing | **是** | **High**；`temporal_agg true→false` |
| `XPolicyLab/ACT/model.py` | Behavior-changing + instrumentation | **是** | **High**；无条件 RGB→BGR；GT replay 未启用 |
| `XPolicyLab/ACT/detr/act_policy.py` | Compatibility + conditional behavior | 部分 | Medium/High；支持 query/aggregation/ckpt override；temporal buffer 初始化缩进依赖 `ACT_QUERY_FREQ`，与官方 true 模式组合存在风险 |
| `XPolicyLab/ACT/utils.py` | Behavior-changing in training | checkpoint 已受影响 | **High provenance**；将 action 对齐固定为 `action[start_ts:]`，不再对 `is_sim=None` 做 -1 shift |
| XPolicyLab 其余 dirty 文件 | Compatibility / offline training / instrumentation | 否 | Low for Day 5；conda 初始化、lazy h5py、resume/loss history 等 |
| `third_party/curobo` gitlink | Compatibility / unrelated to joint path | 否 | Low；本次直接 joint target 评测不走 cuRobo IK/MotionGen |

Day 5 日志确认默认 triangle-mesh 分支实际生效：

- `vertical_coin_stand_0_2 ... enabled triangle-mesh collision`
- `piggy_bank_0_3 ... enabled triangle-mesh collision`

Day 5 metadata 也确认 `GRIPPER_EPS`、`ACT_QUERY_FREQ`、`ACT_TEMPORAL_AGG`、
`ACT_NO_INTERP` 和 `ACT_GRIPPER_MIN_POSITION` 均未设置；`ACT_DEBUG_STOP_STEP` 已移除。

## 版本矩阵

完整矩阵和 `pip check` 见 [dependency_matrix.md](week02_day06/dependency_matrix.md)。

关键结论：

- Isaac Sim 5.1、IsaacLab pin、Python、PyTorch 和 sim NumPy 与官方安装基线一致；
- local RoboDojo 落后 20 commits，但官方没有修改 Coin task、X5、reward、control 或 geometry；
- sim env 的 WebSockets 16.1.1 与 Isaac Sim 声明的 12.0 冲突，但又满足最新 XPolicyLab
  `>=14`；这是官方跨环境约束张力和复现风险，不是已观察到的运行故障；
- cuRobo checkout 偏离 pin，但与本次 joint action path 的相关性低。

## Checkpoint 兼容性

### Action schema

Pass。checkpoint 和 `dataset_stats.pkl` 都是 14-D：

```text
0..5   left arm
6      left gripper normalized
7..12  right arm
13     right gripper normalized
```

训练数据左右 gripper 范围均约为 `[0, 1]`。运行时按 X5 官方
`gripper_scale=[-0.01, 0.044]` 转换到物理 target，再受 runtime soft limit
`[0, 0.044]` 限制。这一范围差异属于官方资产/运行时组合，不是本地 dirty diff 引入；
它会令 normalized 0 的 `-0.01 m` 饱和到 `0 m`，仍应保留为控制语义验证项。

### Camera order and color

Order Pass：训练配置、processed HDF5 和部署配置都包含三路相机，模型顺序均为：

`cam_head → cam_right_wrist → cam_left_wrist`

Color contract Fail/Unknown：processed data 通过 `decode_image_bit` 后原样写入；官方最新
XPolicyLab 明确这些数组应解释为 RGB。当前 runtime adapter 又无条件执行 RGB→BGR。
没有 checkpoint manifest 证明本模型训练在 BGR 数据上，且本地 `model.py` 修改时间晚于
checkpoint。因此当前最有证据的判断是“运行时视觉通道偏离训练/官方契约”，而不是
“BGR 转换必要”。

### Dataset statistics

Pass。现有 processed dataset 包含 100 episodes、18466 个原始 frames，episode 长度
105..205。按训练代码补齐到 `(100, 205, 14)` 后重新计算：

- action mean 最大误差：`5.96e-8`
- action std 最大误差：`0`
- qpos mean 最大误差：`2.98e-8`
- qpos std 最大误差：`0`

因此 stats 与当前 processed data 是同一数据体系，不是错拷贝的统计文件。

### Code and layout provenance

Partial/Unknown。目录名、训练日志和数据路径确认 task/environment/action 为
`deposit_coin/arx_x5/joint`，训练日志记录 1000 epochs，best validation loss
`0.095652 @ epoch 844`。action alignment 源文件时间早于 stats/checkpoint，支持该
checkpoint 使用本地 fixed alignment，但文件时间不是可重建的 commit 证明。

checkpoint 目录没有 Git commit、完整训练 config、数据 revision 或 layout manifest。
原始/processed HDF5 也没有 layout/seed attribute。因此不能证明 checkpoint 专属于 layout 0，
只能确认它来自 arx_x5 的 100 条 deposit_coin 数据；也不能从现有材料重建精确训练代码版本。

## 官方代码差异

详见 [upstream_diff_summary.md](week02_day06/upstream_diff_summary.md)。

官方 RoboDojo 最新相对本地 HEAD 的相关变化只有 WebSocket keepalive 和可选 articulation
drive reset；后者针对 SpringButton 等 `reset_drive=true` 对象，不适用于 Coin 场景。
官方最新没有 Coin-X5 碰撞、摩擦、夹爪映射、lift 或 bbox 修复。

官方 XPolicyLab 保持 ACT `temporal_agg=true`，并在共享代码中把 RGB 契约写成明确结论。
因此本地 false aggregation 和 RGB→BGR 不是官方修复，而是本地行为偏离。

## 官方 Issue 对照

详见 [issue_matrix.md](week02_day06/issue_matrix.md)。

没有公开 Issue 直接匹配 `deposit_coin + arx_x5 + ACT` 或当前“夹爪闭合但 coin pose
不动”的症状。最接近的 Issue 分别涉及 articulation reset、Isaac/driver 启动崩溃和其他
policy 的 checkpoint contract；对象或症状均不足以直接套用。

## 高风险差异

1. **RGB→BGR**：官方契约与本地 runtime adapter 冲突；最可能改变策略抓取姿态。
2. **`temporal_agg=false`**：官方默认 true；改变查询频率、chunk 消费和动作平滑时序。
3. **默认 triangle-mesh collision**：直接改变 stand/piggy bank 物理基线，Day 5 已生效。
4. **训练 action alignment + 缺失 provenance manifest**：checkpoint 与本地 fixed alignment
   有时间证据，但无法由 commit/config 完整重建。

## 中风险差异

- RoboDojo 落后 20 commits，尽管没有 Coin 相关修复；
- sim env WebSockets/Starlette 声明冲突；
- ACT NumPy 2.4.4 需要兼容 unpickler；
- `ACT_GT_REPLAY_LAYOUT_ID=0` 改变 seed list，但符合本次固定 layout 目标；
- local temporal buffer 初始化与官方 true 模式组合存在潜在错误，不能直接只切 YAML 后评测。

## 已排除或低风险差异

- reward/lift/bbox 本地改动只记录日志，判定公式等价；
- Coin friction override 未启用，0.6/1.5 来自官方默认，不是本地 override；
- gripper epsilon override 未启用，仍为 0.2；
- no-interp、direct replay、gripper minimum、debug stop、scene offset/yaw 均未启用；
- 官方 articulation reset fix 不适用于本任务；
- cuRobo 偏离不在正式 joint target 执行路径；
- Isaac Sim 5.1 本身是官方支持组合，且基础仿真/渲染/300 步均通过。

## 结论

当前环境**确实偏离官方行为基线**，主要发生在 ACT 图像通道、temporal aggregation 和
geometry collision，而不是 RoboDojo 最新主仓库缺少 Coin 专项修复。版本或本地修改
**可能参与失败**，但现有单条轨迹不足以将任一差异认定为根因。

Day 7 应使用同一 checkpoint/seed/layout 做单变量、非破坏性对照，优先级为：

1. 保持其余配置不变，对比 runtime RGB 与本地 RGB→BGR；
2. 在先修正/隔离 temporal buffer 初始化后，对比官方 `temporal_agg=true` 与当前 false；
3. 对比官方 geometry collision 与本地 triangle-mesh collision，并记录指尖接触和 coin pose。

这三项可以直接证伪当前最高风险差异，且不需要升级依赖或覆盖 dirty worktree。
