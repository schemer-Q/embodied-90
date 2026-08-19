# Week 2 Day 1: Simulation and Rendering Validation

## 配置

| 项目 | 值 |
| --- | --- |
| RoboDojo commit | `9226f48ea694b3f53db12d4922e8b1199f8d0891` |
| Worktree | dirty；完整清单见 [observation_stats.json](week02_day01/observation_stats.json) 的 `robodojo.status_short` |
| Task / env cfg | `deposit_coin` / `arx_x5` |
| Environment | 1；日志报告 environment device 为 CPU，RTX 渲染使用 `cuda:0` |
| Seed / layout | `0` / `0` |
| Policy | 无；WebSocket client 替换为本地空实现，不启动或加载 ACT |
| Action | 每个 policy step 读取当前双臂 qpos 和夹爪开度，并回写为 position target |
| Task hooks | reset 后禁用 reward step 和 episode-end hook，只保留动作转换、插值、控制器和仿真步进 |
| Steps | 75 policy steps；每步 10 个内部 control/PhysX steps |
| Capture | reset、policy step 37、policy step 75 |

复现入口为 [run_validation.sh](week02_day01/run_validation.sh)，实现见 [run_sim_render_validation.py](week02_day01/run_sim_render_validation.py)。完整控制台输出保存在 [sim_render.log](week02_day01/sim_render.log)。

## 仿真验证

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| 环境创建 | Pass | Isaac Sim 完成启动并创建单环境；JSON `error=null` |
| 场景 reset | Pass | reset 完成，`coin0`、`vertical_coin_stand`、`piggy_bank` 均解析到实例 |
| 物理步进 | Pass | physics/common counter 均从 842 增至 1592，恰好增加 750 |
| 仿真时间更新 | Pass | `3.376000 s -> 6.376000 s`，增加约 3.000 s，与 `750 x 0.004 s` 一致 |
| 机器人 pose 有效 | Pass | 76 个样本中双臂 qpos、夹爪 qpos 和 EE pose 均为有限值 |
| 硬币 pose 有效 | Pass | 76 个 position/quaternion 样本均无 NaN/Inf |
| 静置状态稳定 | Pass | 硬币最大平移 `8.47e-7 m`；未穿模、掉落或明显漂移 |
| hold-position action | Pass | 左右臂 qpos 最大漂移均约 `3.46e-11 rad`，夹爪保持约 `0.044 m` |
| 正常关闭 | Pass | 完成 75/75 后关闭，最终严格检查全部为 true |

完整逐步状态、漂移计算和自动检查见 [observation_stats.json](week02_day01/observation_stats.json)。硬币 quaternion 相对 reset 的最大向量差为 `3.27e-5`，未观察到翻倒或姿态突变。

## 渲染验证

下表给出 reset/final 的 `mean / std`；三路在 mid 帧也保持同一数量级。全部图像均为 `uint8`，范围非零且空间标准差远高于近似恒定阈值 `1.0`。

| 相机 | Shape | Reset mean/std | Final mean/std | 结果 | 视觉观察 |
| --- | --- | --- | --- | --- | --- |
| Head | `480x640x3` | `100.07 / 55.04` | `100.09 / 55.05` | Pass | 双臂、硬币座和存钱罐均在画面内，方向正常 |
| Left wrist | `480x640x3` | `92.50 / 44.68` | `92.53 / 44.70` | Pass | 硬币和两侧指尖位于合理区域，无明显裁切或倒置 |
| Right wrist | `480x640x3` | `130.37 / 64.04` | `130.40 / 64.04` | Pass | 存钱罐投入口和指尖清晰；硬币不在该目标侧近景内 |

reset 到 final 的 mean absolute pixel difference 分别为 Head `0.101`、Left wrist `0.107`、Right wrist `0.100`。该微小变化与静置场景一致，不是冻结帧判定依据；帧有效性主要由每张图的非零动态范围和空间标准差确认。

图像证据：

- Head：[reset](week02_day01/cam_head_reset.jpg) / [mid](week02_day01/cam_head_mid.jpg) / [final](week02_day01/cam_head_final.jpg)
- Left wrist：[reset](week02_day01/cam_left_wrist_reset.jpg) / [mid](week02_day01/cam_left_wrist_mid.jpg) / [final](week02_day01/cam_left_wrist_final.jpg)
- Right wrist：[reset](week02_day01/cam_right_wrist_reset.jpg) / [mid](week02_day01/cam_right_wrist_mid.jpg) / [final](week02_day01/cam_right_wrist_final.jpg)

## 警告分类

### 非致命警告

- `CUDA_VISIBLE_DEVICES` 枚举提示、CPU powersave、IOMMU 和 memory budget interface 性能提示：本次未引发 CUDA/PhysX 错误或中断。
- `dynamic_control`、`pxr.Semantics` deprecation，以及 Replicator category/material configuration 提示：属于 API/扩展兼容性告警。
- Fabric `string[]` 未处理提示：未影响对象 pose、控制计数或 RGB 采集。
- `RTSubframes` 从未设置自动提高到 3：代码已自动规避随机背景纹理产生空帧。

### 可能影响画面的警告

- 三路相机均报告 aperture 与 `4:3` 分辨率不一致，并将 `verticalAperture` 从 `1.52908` 自动调整为 `1.571625`。本次画面有效，但实际内参与声明值可能不完全一致。
- X5 USD 中若干 material binding 指向 reference scope 外部并被忽略；Mahogany MDL 有 `float -> float2` 隐式转换告警。本次材质和场景仍可见，但这些告警可能改变局部外观。

### 需要后续验证的警告

- 若后续使用相机内参做几何定位，应读取运行时 intrinsic matrix，并确认 aperture 自动修正后的值，而不能只依赖 USD 声明。
- USD material binding 和 MDL 告警目前不支持解释 Coin-X5 抓取失败；若后续发现视觉域差异或局部材质缺失，再单独修复资产。
- 本次日志没有 `Invalid PhysX transform`、CUDA error、NaN/Inf 或相机采集异常。

## 结论

**在 seed 0、layout 0、单环境和 75 个 hold-position policy steps 的范围内，基础仿真与三路 RGB 渲染可暂时排除为 Coin-X5 失败的主要原因。**

环境可在不启动 ACT 的情况下完成创建、reset、750 个 PhysX steps、状态更新和正常关闭；机器人及硬币状态为有限值，硬币静置稳定；三路 RGB 均非空帧、非近似恒定帧，且任务相关区域可见。

该结论不验证相机左右语义、精确内参、ACT observation 预处理、动作映射或抓取接触物理，也不外推到其他 seed/layout。Day 2 应继续验证 dual-X5 模型、关节顺序、左右臂语义和初始状态。
