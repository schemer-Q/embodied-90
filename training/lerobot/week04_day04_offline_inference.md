# Week 4 Day 4: Tiny ACT Offline Inference

## 1. 目标

加载 Week 4 Day 3 训练的 Tiny ACT checkpoint，对固定的 PushT observation 执行离线推理，验证 checkpoint、预处理、ACT forward、action queue 和后处理能够形成完整链路。本实验不启动环境，也不评价策略控制质量。

## 2. 固定输入

| 项目 | 值 |
| --- | --- |
| Dataset | `lerobot/pusht` |
| Revision | `b1c3ecbae7f244acc039a3dbc255a00dad1372b9` |
| Episode | `0` |
| Frames | `0, 80, 160` |
| Seed | `20260907` |
| Observation image | RGB `float32 [3,96,96]` |
| Observation state | `float32 [2]` |
| Action | `float32 [2]` |

三帧分别覆盖 episode 起始、中间和末尾。原始输入、归一化输入的 shape、dtype、范围和 tensor SHA256 均记录在 [`week04_day04/inference_results.json`](week04_day04/inference_results.json)，可视化见 [输入快照](week04_day04/input_snapshot.png)。

## 3. Checkpoint 与处理链

| 项目 | 值 |
| --- | --- |
| Checkpoint | `week04_day03/run/checkpoints/last/pretrained_model` |
| Model SHA256 | `d5a0afde02ee7185bf2b6a83417031c66905e09cd39a6e2714fd3082421fb6f8` |
| Loader | `ACTPolicy.from_pretrained` |
| Pre/postprocessor | `make_pre_post_processors(..., pretrained_path=checkpoint)` |
| Device | CUDA，NVIDIA GeForce RTX 5070 |
| ACT chunk | `[1,10,2]` |
| Executed action steps | `10` |

checkpoint 自带的 preprocessor 执行 batch、CUDA device 和 observation normalization；postprocessor 将模型输出反归一化为 PushT 的二维 action 坐标。推理代码没有使用数据集 action 作为模型输入，ground-truth action 只在输出后用于数值对照。

复现命令：

```bash
bash training/lerobot/week04_day04/run_offline_inference.sh
```

若 `/tmp` 中的隔离环境不存在，入口会先调用 Day 3 的环境脚本重建 LeRobot 0.4.4 环境。运行固定 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 和 `WANDB_MODE=disabled`，不会下载模型或数据。

## 4. 推理结果

| Frame | First predicted action | Ground truth action | L2 difference | Chunk latency |
| ---: | --- | --- | ---: | ---: |
| 0 | `[189.5971, 310.4897]` | `[233.0, 71.0]` | `243.3909` | `182.70 ms` |
| 80 | `[161.1664, 299.2339]` | `[260.0, 191.0]` | `146.5696` | `1.82 ms` |
| 160 | `[162.3583, 317.8791]` | `[164.0, 355.0]` | `37.1572` | `1.83 ms` |

frame 0 时延包含首次 CUDA kernel/context 初始化，后续两帧更能代表热身后的单次 chunk forward。峰值已分配显存为 `66.01 MiB`。

50-step、单 episode 的 Tiny ACT 尚未充分训练，预测 action 与数据集 action 的差异不能用于判断模型实现错误，也不能据此评价泛化或控制效果。

## 5. 完整性检查

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| Checkpoint 加载 | Pass | 本地权重与 processor 全部加载 |
| 模型参数有限 | Pass | 无 NaN/Inf |
| 起始/中间/末尾推理 | Pass | frame `0/80/160` |
| Action shape | Pass | 三组均为 `[1,10,2]` |
| Action 数值 | Pass | 归一化及反归一化结果均有限 |
| 同 seed 重复 | Pass | 三帧均 bitwise equal |
| Action queue | Pass | `select_action` 的 10 个结果与 direct chunk 逐位一致 |
| 离线执行 | Pass | Hub 和 W&B 均禁用 |

逐 action 记录及各次 `select_action` 时延见 [`week04_day04/inference_trace.csv`](week04_day04/inference_trace.csv)，紧凑摘要见 [`inference_summary.json`](week04_day04/inference_summary.json)，完整终端输出见 [`inference.log`](week04_day04/inference.log)。

## 6. 结论与边界

Week 4 Day 4 验收通过：Day 3 checkpoint 可以独立加载，保存的 normalization statistics 正常生效，三个固定 observation 均可在 CUDA 上生成有限的二维 action chunk，后处理和逐步 action queue 行为一致，同 seed 重复推理可复现。

本结论只证明离线推理链路正确，不证明 Tiny ACT 已学会 PushT，也不证明 action 能在环境中完成任务。Day 5 将基于本次 trace 专门解释 chunk 生成、queue 消费、归一化和时序窗口。
