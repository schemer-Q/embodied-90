# Week 4 Day 2: LeRobot Dataset Download and Visualization

## 1. 目标

下载一个小型公开 LeRobot v3 数据集，通过固定版本的官方 `LeRobotDataset` API 检查 metadata、episode、tensor 和视频语义，并生成可重复的无 GUI 可视化。

参考：[固定的 PushT 数据 revision](https://huggingface.co/datasets/lerobot/pusht/tree/b1c3ecbae7f244acc039a3dbc255a00dad1372b9) 和 [LeRobotDataset v3 官方说明](https://github.com/huggingface/lerobot/blob/main/docs/source/lerobot-dataset-v3.mdx)。

## 2. 固定配置

| 项目 | 值 |
| --- | --- |
| Dataset | `lerobot/pusht` |
| Dataset revision | `b1c3ecbae7f244acc039a3dbc255a00dad1372b9` |
| Dataset codebase version | `v3.0` |
| Selected episode | `0` |
| LeRobot | `0.4.4` |
| Python | `3.11.15` |
| PyTorch | `2.7.0+cu128` |
| Torchvision | `0.22.0+cu128` |
| Video backend | `pyav` |
| Local dataset size | `7,680,844 bytes` |

精确环境见 [`week04_day02/environment.json`](week04_day02/environment.json) 和 [`environment.lock.txt`](week04_day02/environment.lock.txt)。数据文件逐项 SHA256 见 [`dataset_manifest.json`](week04_day02/dataset_manifest.json)。原始数据保存在被 `.gitignore` 排除的 `week04_day02/dataset/`。

## 3. 环境兼容性

首次使用系统 Python 3.12、PyTorch `2.12.1`、Torchvision `0.27.1` 时，metadata 和 episode table 能加载，但视频解码失败：LeRobot `0.4.4` 的 `pyav` 路径调用 `torchvision.io.VideoReader`，而 Torchvision `0.27.1` 已不提供该接口。

正式验证改用现有 RoboDojo Python 3.11 的 PyTorch `2.7.0` / Torchvision `0.22.0` 作为 base，并在 `/tmp` 创建隔离的 data-only 环境。此组合位于 LeRobot `0.4.4` 声明的版本范围内，且 `VideoReader` 可用。解码时的 Torchvision deprecation warning 非致命，但说明后续升级需要切换 TorchCodec 或复核新版 LeRobot。

复现命令：

```bash
bash training/lerobot/week04_day02/setup_environment.sh
bash training/lerobot/week04_day02/run_validation.sh
```

该环境只证明数据读取链路可用，不等同于 Week 4 Day 3 的完整 ACT 训练环境。

## 4. 数据集结构

下载数据由六个核心文件组成：

```text
data/chunk-000/file-000.parquet
meta/episodes/chunk-000/file-000.parquet
meta/info.json
meta/stats.json
meta/tasks.parquet
videos/observation.image/chunk-000/file-000.mp4
```

`info.json` 记录：

- `206` episodes；
- `25,650` frames；
- `10 FPS`；
- `1` 个 task；
- 一个 `96 x 96` 视频字段；
- `observation.state` 和 `action` 均为二维。

完整字段与 Parquet 类型见 [`schema.json`](week04_day02/schema.json)。data Parquet 包含：

```text
observation.state, action, episode_index, frame_index, timestamp,
next.reward, next.done, next.success, index, task_index
```

episode metadata 通过 `dataset_from_index` / `dataset_to_index` 记录全局帧边界，并单独记录视频时间范围，证实 v3 episode 边界来自 metadata，而不是文件边界。

## 5. Episode 0 验证

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| API/Parquet 长度 | Pass | 均为 `161` frames |
| Episode 边界 | Pass | 全局索引 `[0,161)` |
| Frame index | Pass | 连续 `0..160` |
| Timestamp | Pass | `0.0..16.0 s`，平均间隔 `0.1000000015 s` |
| Timestamp/FPS | Pass | 最大间隔误差 `5.74e-7 s` |
| Task mapping | Pass | 全程 `task_index=0` |
| State/action finite | Pass | 未发现 NaN/Inf |
| 末帧终止标志 | Pass | `next.done=true` |

Task 为：`Push the T-shaped block onto the T-shaped target.`

本 episode 的数值范围：

| 字段 | Min | Max |
| --- | --- | --- |
| `observation.state[0]` | `93.702` | `373.731` |
| `observation.state[1]` | `84.280` | `448.178` |
| `action[0]` | `93.0` | `375.0` |
| `action[1]` | `71.0` | `449.0` |

这些是 PushT 的二维平面坐标，不是 dual-X5 joint。不能用其尺度推断 RoboDojo 关节归一化。

## 6. 图像契约

| 层级 | Shape/layout | Dtype/range | Color |
| --- | --- | --- | --- |
| `info.json` | `[96,96,3]` HWC | video | 未直接声明 |
| PyAV raw decode | `[96,96,3]` HWC | `uint8 [0,255]` | 显式 `rgb24` |
| `LeRobotDataset[index]` | `[3,96,96]` CHW | `float32 [0,1]` | RGB |

首帧对照结果：

- raw RGB vs API image MAE：`0.0`；
- raw R/B swapped vs API image MAE：`1.14569`；
- 结论：当前固定版本的 dataset API 将视频输出为 RGB、CHW、归一化 float tensor。

这只验证公开 PushT 数据及 LeRobot API，不自动证明 RoboDojo v3 转换器写入的三路视频颜色正确。后者仍需在产生本地转换样本后独立检查。

## 7. 可视化

- [首/中/末三帧](week04_day02/visualizations/episode0_contact_sheet.png)
- [State/action 轨迹](week04_day02/visualizations/episode0_state_action.png)
- 单帧文件位于 `week04_day02/visualizations/`

人工检查结果：三帧均非空，T-shaped block、目标和控制器位置随 episode 推进发生合理变化；state/action 曲线连续，无空数据或明显断裂。

## 8. 验收结论

- Pass：固定 revision 的公开 LeRobot v3 数据已下载并记录哈希；
- Pass：`LeRobotDataset` 可加载、解码和索引 episode 0；
- Pass：metadata、Parquet 与 API 的 episode 长度和字段一致；
- Pass：frame index、timestamp、task、state/action 完整且有效；
- Pass：已明确磁盘 HWC 与 API CHW，以及 API 的 RGB 颜色语义；
- Pass：已生成可审阅的图像和轨迹可视化；
- Boundary：样本只有单相机、二维 state/action，不能替代 dual-X5 三相机 14 维数据验证；
- Risk：Day 3 训练前必须重新确认完整 policy 依赖，不能直接把本日 data-only 环境作为训练环境。

Week 4 Day 2 验收通过。
