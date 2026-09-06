# Week 4 Day 3: Tiny ACT Training

## 1. 目标

在 RTX 5070 上使用官方 LeRobot `lerobot-train` 完成极小规模 ACT 训练，验证固定数据能够经过 dataloader、预处理、forward、backward 和 optimizer step，并形成可加载 checkpoint。目标不是训练可部署策略或评估任务成功率。

## 2. 环境

| 项目 | 值 |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5070，12,227 MiB，compute capability 12.0 |
| Driver | `570.211.01` |
| Python | `3.11.15` |
| PyTorch | `2.7.0+cu128` |
| Torchvision | `0.22.0+cu128` |
| LeRobot | `0.4.4` |
| CUDA available | `true` |
| W&B | disabled |
| Hub access during training | offline |

精确环境见 [`week04_day03/environment.json`](week04_day03/environment.json) 和 [`environment.lock.txt`](week04_day03/environment.lock.txt)。环境基于 RoboDojo 的 Torch/CUDA 栈创建隔离 venv，没有修改 RoboDojo 环境。

复现命令：

```bash
bash training/lerobot/week04_day03/setup_training_environment.sh
bash training/lerobot/week04_day03/train_tiny.sh
/tmp/embodied90-week04-day02-lerobot/bin/python \
  training/lerobot/week04_day03/analyze_training.py \
  --artifact-dir training/lerobot/week04_day03
/tmp/embodied90-week04-day02-lerobot/bin/python \
  training/lerobot/week04_day03/verify_parameter_update.py
```

## 3. 数据与输入契约

| 项目 | 值 |
| --- | --- |
| Dataset | `lerobot/pusht` |
| Revision | `b1c3ecbae7f244acc039a3dbc255a00dad1372b9` |
| Episodes | `[0]` |
| Frames | `161` |
| Observation image | RGB `float32 [3,96,96]` |
| Observation state | `float32 [2]` |
| Action | `float32 [2]` |
| Action query | `10 x 2`，episode 边界由 padding mask 处理 |

训练直接读取 Day 2 已固定并校验哈希的数据目录，不进行网络下载。该二维 PushT action 只用于打通训练链路，不代表 dual-X5 的 14 维动作契约。

## 4. 最小 ACT 配置

| 参数 | 值 |
| --- | --- |
| Vision backbone | ResNet18，随机初始化 |
| Pretrained backbone | disabled |
| Transformer width | `128` |
| Attention heads | `4` |
| Feed-forward width | `256` |
| Encoder/decoder layers | `1 / 1` |
| VAE encoder layers | `1` |
| Latent dimension | `16` |
| Chunk/action steps | `10 / 10` |
| Batch size | `2` |
| Optimizer | AdamW，LR `1e-5` |
| Seed | `20260906` |
| Optimizer steps | `50` |
| AMP | disabled |
| Evaluation | disabled |

完整生成配置见 [`week04_day03/training_config.json`](week04_day03/training_config.json)。模型共有 `11,705,954` 个可训练参数。

## 5. 训练结果

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| Process exit | Pass | exit code `0` |
| Optimizer steps | Pass | `50/50` |
| Forward/backward | Pass | 50 条 loss/gradient 记录 |
| Loss finite | Pass | 全部有限 |
| Gradient finite/nonzero | Pass | `50/50` steps |
| GPU execution | Pass | 峰值显存 `1,437 MiB`，峰值利用率 `29%` |
| OOM | Pass | 未发生 |
| Checkpoint save | Pass | step 50 checkpoint |
| Checkpoint load | Pass | `ACTPolicy.from_pretrained` 成功 |
| Checkpoint parameters | Pass | 全部有限 |

Loss 摘要：

- first：`53.450`；
- last：`40.738`；
- min/max：`38.639 / 56.229`；
- first 10 mean：`51.8497`；
- last 10 mean：`42.4927`；
- 后 10 步均值较前 10 步低约 `18.0%`。

mini-batch loss 并非单调下降，50 steps 也不足以证明收敛；这里只将有限 loss、非零 gradient 和参数更新视为训练链路证据。详见 [`metrics.json`](week04_day03/metrics.json) 和 [训练曲线](week04_day03/loss_curve.png)。

## 6. 参数更新与 Checkpoint

使用同一 seed 和同一模型配置重建初始 ACT，再与训练 checkpoint 逐项比较：

| 指标 | 值 |
| --- | --- |
| Changed state values | `8,419,857 / 11,726,690` |
| L2 difference | `0.2557459` |
| Maximum absolute difference | `0.00052094` |

因此 checkpoint 不只是初始化模型的重复保存。完整结果见 [`parameter_update.json`](week04_day03/parameter_update.json)。

最终模型：

- local path：`week04_day03/run/checkpoints/last/pretrained_model`；
- `model.safetensors` SHA256：`d5a0afde02ee7185bf2b6a83417031c66905e09cd39a6e2714fd3082421fb6f8`；
- 模型权重：`46,923,864 bytes`；
- 完整 checkpoint：`140,626,805 bytes`。

checkpoint 位于 `.gitignore` 排除的 `run/`，避免把模型和 optimizer state 提交到 Git；逐文件路径、大小和 SHA256 保存在 [`checkpoint_manifest.json`](week04_day03/checkpoint_manifest.json)。Day 4 离线推理使用该本地 checkpoint。

## 7. 警告与边界

- 非致命：未安装 TorchCodec，LeRobot 回退到 PyAV；
- 非致命：Torchvision `VideoReader` 已标记弃用，但本次解码正常；
- 环境边界：系统 Torchvision `0.27.1` 不兼容本版本 PyAV 路径，本次固定使用 `0.22.0`；
- 结果边界：只训练一个 episode、50 steps，不评价泛化、控制质量或任务成功率；
- 数据边界：PushT 是单相机二维任务，不等价于 RoboDojo dual-X5。

## 8. 验收结论

Week 4 Day 3 验收通过：官方 ACT 训练链路已在 RTX 5070 上完成 50 次真实 optimizer update，loss/gradient 有限，GPU 参与计算，模型参数发生变化，最终 checkpoint 已保存、校验哈希并成功重新加载。该 checkpoint 可以进入 Day 4 离线推理验证。
