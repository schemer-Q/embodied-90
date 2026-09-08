# Week 4 Day 5: ACT Chunking, Normalization, and Temporal Windows

## 1. 目标

基于 Week 4 Day 3 的 Tiny ACT checkpoint 和 Day 4 的离线推理链路，验证训练 action window、mean/std normalization、推理 action queue、episode 尾部 padding loss，以及当前 queue 模式与 temporal ensembling 的区别。

## 2. 固定配置

| 项目 | 值 |
| --- | --- |
| LeRobot | `0.4.4` |
| Dataset | `lerobot/pusht` |
| Revision | `b1c3ecbae7f244acc039a3dbc255a00dad1372b9` |
| Episode | `0`，共 `161` frames |
| FPS | `10` |
| Frames inspected | `0, 80, 160` |
| Chunk size | `10` |
| Executed action steps | `10` |
| Temporal ensemble coefficient | `null` |
| Seed | `20260908` |

复现命令：

```bash
bash training/lerobot/week04_day05/run_analysis.sh
```

## 3. 训练时序窗口

`ACTConfig.action_delta_indices` 返回 `[0,1,...,9]`。`resolve_delta_timestamps` 使用数据集 `10 Hz` FPS 将其转换为：

```text
action: [t, t+0.1, t+0.2, ..., t+0.9 seconds]
```

因此每个训练样本包含 `[10,2]` action target。`observation_delta_indices=null`，图像和 state 只取当前时刻，不包含历史帧堆叠。

| Anchor frame | 有效 action | Padding | 解析后的 frame 范围 |
| ---: | ---: | ---: | --- |
| 0 | 10 | 0 | `0..9` |
| 80 | 10 | 0 | `80..89` |
| 160 | 1 | 9 | `160` 后重复边界值并标记 padding |

完整 target、请求索引、边界裁剪索引和 mask 见 [`week04_day05/temporal_window.json`](week04_day05/temporal_window.json)。

## 4. 归一化

当前 checkpoint 对视觉、state 和 action 均使用 `MEAN_STD`：

```text
normalize(x)   = (x - mean) / (std + 1e-8)
unnormalize(z) = z * std + mean
```

手工公式与 checkpoint processor 在 frame `0/80/160` 上逐项比较：

| 检查 | 最大绝对误差 | 结果 |
| --- | ---: | --- |
| Image/state/action normalization | `0.0` | Pass |
| Action manual unnormalize vs postprocessor | `0.0` | Pass |
| Action raw → normalize → unnormalize round trip | `1.53e-5` | Pass |

processor 的统计来自 PushT 数据集元数据，其中 state/action count 为 `25,650`，视觉统计 count 为 `19,619`；它们并非只对训练所选 episode 0 的 161 帧重算。完整 count、mean/std 和逐帧对照见 [`week04_day05/normalization_check.json`](week04_day05/normalization_check.json)。

## 5. Action Chunk 与 Queue

当前 `temporal_ensemble_coeff=null`，因此 `ACTPolicy.select_action` 使用 `_action_queue`：

1. queue 为空时调用 `predict_action_chunk`，得到 `[batch=1, chunk=10, action_dim=2]`；
2. 将前 `n_action_steps=10` 项放入 queue；
3. 当前调用立即弹出 index 0，queue 剩 9 项；
4. 后续 9 次调用只消费 queue，不执行模型 forward；
5. 第 11 次调用 queue 已空，生成下一个 chunk。

对固定 frame 80 连续调用 `select_action` 21 次并对底层 `policy.model` 计数：

| 指标 | 实测 |
| --- | --- |
| `select_action` calls | `21` |
| Model forwards | `3` |
| Forward/refresh calls | `1, 11, 21` |
| Expected refresh calls | `1, 11, 21` |
| 结论 | Pass |

逐调用 queue 长度、chunk/index、forward 标记和 action 见 [`week04_day05/chunk_trace.csv`](week04_day05/chunk_trace.csv)，图示见 [`chunk_window_plot.png`](week04_day05/chunk_window_plot.png)。

## 6. Episode 尾部 Padding 与 Loss

frame 160 的 `action_is_pad` 为 `[false,true,...,true]`，即只有 offset 0 有效。ACT 的 L1 计算为：

```text
mean(abs(target - prediction) * ~action_is_pad)
```

固定随机种子后执行两项实际模型对照：

| 条件 | Total loss | L1 loss |
| --- | ---: | ---: |
| Baseline | `40.578655` | `0.040403` |
| 9 个 padded targets 全部 `+123` | `40.578655` | `0.040403` |
| 唯一有效 target `+1` | `42.764503` | `0.124083` |

修改 padded target 不改变 VAE encoder 或 L1 loss，修改有效 target 会改变 loss，证明 mask 生效。

需要注意：实现先将 padded term 乘为零，再对完整 `[batch,chunk,action_dim]` tensor 调用 `.mean()`。因此 padding 不贡献 loss 分子，但仍占 mean 的分母；有效 target 较少的尾部样本其 L1 数值会按完整 chunk 大小缩小。合成数值验证和实际模型结果见 [`week04_day05/padding_loss_check.json`](week04_day05/padding_loss_check.json)。

## 7. Queue 与 Temporal Ensembling

| 行为 | 当前 queue 模式 | Temporal ensembling |
| --- | --- | --- |
| 配置 | `temporal_ensemble_coeff=null` | coefficient 非 `null` 且 `n_action_steps=1` |
| 模型查询频率 | 每 10 个 action 一次 | 每个环境 step 一次 |
| 单次预测 | 10-step chunk | 10-step chunk |
| 当前 action | 顺序消费一个 chunk | 融合覆盖当前时刻的多个历史 chunk 预测 |
| 状态 | `_action_queue` | `ACTTemporalEnsembler` 在线缓存 |

LeRobot 0.4.4 的正 coefficient 使用指数权重，并给予较旧预测更高权重；默认示例系数为 `0.01`。今天没有修改 checkpoint 配置或运行 temporal ensemble 对照，只确认了两条代码路径的语义。

函数与当前环境行号见 [`week04_day05/source_index.json`](week04_day05/source_index.json)。这些绝对路径位于可重建的 `/tmp` venv，稳定定位应以 LeRobot `0.4.4` 的函数名为准。

## 8. 验收结论

Week 4 Day 5 验收通过：训练 action window 为 `[t..t+9]`，当前 observation 没有历史窗口；checkpoint 的 mean/std processor 与手工公式一致；当前策略逐步消费完整 10-action chunk，仅在 queue 为空时重新 forward；末尾 padding target 不参与模型和 L1 有效项，但保留在 mean 分母；queue 模式与 temporal ensembling 的查询和融合语义已明确区分。

以上结论解释数据和推理时序，不评价 Tiny ACT 的任务能力。
