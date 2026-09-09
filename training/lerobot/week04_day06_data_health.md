# Week 4 Day 6: LeRobot Dataset Health Checker

## 1. 目标

将 Week 4 Day 1～5 使用的 LeRobot 数据契约固化为只读 CLI，对目录结构、metadata、Parquet、episode、时间戳、state/action、视频、API tensor 和 ACT action window 给出机器可读的 `PASS/WARN/FAIL` 结果。

## 2. 使用方式

本次 PushT 基线：

```bash
bash training/lerobot/week04_day06/run_health_check.sh
```

通用 CLI：

```bash
python training/lerobot/week04_day06/check_dataset.py \
  --root /path/to/local/dataset \
  --repo-id owner/dataset \
  --revision REVISION \
  --expected-state-dim 14 \
  --expected-action-dim 14 \
  --expected-camera observation.images.cam_high \
  --expected-camera observation.images.cam_left_wrist \
  --expected-camera observation.images.cam_right_wrist \
  --action-window 100 \
  --output /path/to/report
```

`--expected-*` 参数用于把数据集自身声明的 schema 与部署方预期分开验证。错误返回退出码 `1`；默认 warning 不改变退出码，加入 `--strict-warnings` 后 warning 也返回非零。脚本不写入数据集目录。

## 3. 检查范围

| 类别 | 检查 |
| --- | --- |
| Structure | v3 metadata、Parquet 和视频引用文件存在 |
| Schema | 必需字段、声明 shape、Parquet fixed-list dimension、预期维度 |
| Counts | frame、episode、task 数与 `info.json` 一致 |
| Episodes | episode index、边界、length 和 frame index 连续 |
| Time | 每个 episode timestamp 等于 `frame_index / fps` |
| Values | 全量 state/action 无 NaN/Inf，min/max 与 stats 一致 |
| Tasks | 所有 frame 的 `task_index` 均能解析 |
| Video | 完整解码、帧数、FPS、shape、首帧非恒定 |
| API samples | 九个均匀抽样位置的 feature 存在，tensor dtype/shape/range 有效 |
| ACT window | 首帧完整 window，末帧 padding mask 正确 |

全量检查覆盖所有 `25,650` 条 Parquet frame 和整个视频；视觉 tensor 内容统计采用九个均匀位置抽样。脚本只确认结构和基础数值健康，不判断 demonstration 是否优质，也不能从数值自动证明 14-D action 的左右臂语义顺序。

## 4. PushT 正式结果

| 指标 | 结果 |
| --- | --- |
| Overall | `PASS` |
| Checks | `35 PASS / 0 WARN / 0 FAIL` |
| Frames | `25,650` |
| Episodes | `206` |
| Tasks | `1` |
| State/action dim | `2 / 2` |
| Episode length | min `49`，max `246`，mean `124.51` |
| Video | AV1/yuv420p，`96x96 @ 10 Hz` |
| Decoded video frames | `25,650 / 25,650` |
| ACT window | `10` actions，末帧 `1` valid + `9` padded |

正式机器可读结果见 [`week04_day06/health_report.json`](week04_day06/health_report.json)，逐项表格见 [`checks.csv`](week04_day06/checks.csv)，自动生成的人类可读报告见 [`health_report.md`](week04_day06/health_report.md)。

Torchvision 提示 `VideoReader` 将弃用并建议迁移 TorchCodec；本次 LeRobot 0.4.4 使用 PyAV 成功完成解码，该提示不构成数据失败。

## 5. 失败检测验证

[`test_health_checks.py`](week04_day06/test_health_checks.py) 使用纯内存或 `/tmp` 临时目录验证：

- state/action 中出现 NaN 会被判定为无效；
- 10 Hz timestamp 从 `0.1` 跳到 `0.3` 会被判定为不连续；
- 必需文件缺失会被列出。

三项负向单元测试全部通过。另以不存在的数据集目录执行完整 CLI：进程按预期返回退出码 `1`、报告为 `2 FAIL`，且仍成功生成 `health_report.json`、`checks.csv` 和 `health_report.md`。负向单元测试日志见 [`negative_tests.log`](week04_day06/negative_tests.log)。

## 6. 产物与边界

- [`check_dataset.py`](week04_day06/check_dataset.py)：通用只读检查器；
- [`run_health_check.sh`](week04_day06/run_health_check.sh)：固定 PushT 基线入口；
- [`health_check.log`](week04_day06/health_check.log)：正式运行日志；
- `health_report.json`：适合 CI 或后续自动汇总；
- `checks.csv`：逐项状态和证据；
- `health_report.md`：由同次运行自动生成。

当前脚本针对 LeRobot v3 本地数据目录。视频健康检查验证可解码、帧数、基础 range 和非恒定性，不执行语义级画面质量检测；多相机数据可通过重复 `--expected-camera` 检查声明和引用，但本次 PushT 只有单相机。

## 7. 验收结论

Week 4 Day 6 验收通过：数据健康检查器可复现运行，PushT 固定数据通过 35 项检查，完整视频和 frame metadata 自洽；负向测试及失败集成测试证明异常会被识别并返回非零退出码；CLI 已保留 dual-X5 14-D state/action 和三相机预期参数。
