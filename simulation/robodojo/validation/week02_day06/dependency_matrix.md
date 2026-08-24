# Dependency Matrix

审计时间：2026-08-24。版本来自运行环境、Git object 和官方仓库；未安装或升级任何依赖。

| 组件 | 本地版本 | 官方基线/要求 | 匹配 | 风险与结论 |
|---|---|---|---|---|
| RoboDojo | `9226f48`，dirty | 最新 `2184bf8` | 否，落后 20 commits | Medium。最新未改 Coin、X5、reward 或控制器；新增 articulation drive reset 不适用于本任务 |
| XPolicyLab | checkout `3e6b42c`，ACT dirty | RoboDojo 最新 pin `432f82b`；XPolicyLab 最新 `c07a096` | 否 | High。官方已明确统一 RGB；本地 ACT 强制 RGB→BGR，且 temporal aggregation 被关闭 |
| Isaac Sim | `5.1.0.0` | `5.1.0` | 是 | Low。官方仍固定 5.1；Day 1/5 已完整启动、渲染和运行 |
| IsaacLab | package `0.54.3`；commit `afca7b0` | RoboDojo 最新 pin `afca7b0` | 是 | Low |
| cuRobo | commit `895c651` | local/official pin `d17b54c` | 否 | Low for joint eval。差异含 X5/Isaac Sim 适配，但本次 14-D joint target 路径不使用 cuRobo 规划 |
| Python | `3.11.15` | `>=3.11` / install 创建 3.11 | 是 | Low |
| PyTorch | `2.7.0+cu128` | `2.7.0`, CUDA 12.8 index | 是 | Low |
| Gymnasium | `1.2.1` | 未在 RoboDojo install 中精确固定 | Unknown | Low；基础环境已通过，但不能称为严格版本匹配 |
| NumPy (sim) | `1.26.0` | `1.26.0` | 是 | Low |
| NumPy (ACT) | `2.4.4` | XPolicyLab `>=1.23`，无上限 | 范围内 | Medium。需本地兼容 unpickler 读取由 NumPy 1.x 写出的 stats |
| WebSockets (sim) | `16.1.1` | RoboDojo install `12.0`；最新 XPolicyLab `>=14.0` | 官方自身存在约束冲突 | Medium compatibility；连接和 300 步运行已通过，不支持将其作为当前行为失败原因 |
| WebSockets (ACT) | `16.1.1` | 最新 XPolicyLab `>=14.0` | 是 | Low |
| OpenCV (ACT) | `5.0.0.93` | XPolicyLab `>=4.8` | 范围内 | Medium。版本未显示运行失败，但图像通道解释属于 High-risk code contract |

## Pip Check

ACT 环境：`No broken requirements found`。

RoboDojo 环境存在两项声明冲突：

- `isaaclab 0.54.3` 要求 `starlette==0.49.1`，本地为 `0.45.3`；
- `isaacsim-kernel 5.1.0.0` 要求 `websockets==12.0`，本地为 `16.1.1`。

两项均需记录为可复现性风险。它们没有造成 Day 1/5 的启动、WebSocket、渲染或完整 episode
失败，因此目前不支持把它们视为 Coin 无法抬升的原因。

## Official Sources

- [RoboDojo install script at official latest](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/2184bf8844ea9d205382c4aefa3a694311418251/scripts/install.sh)
- [RoboDojo official latest commit](https://github.com/RoboDojo-Benchmark/RoboDojo/commit/2184bf8844ea9d205382c4aefa3a694311418251)
- [XPolicyLab official latest commit](https://github.com/XPolicyLab/XPolicyLab/commit/c07a09614dd44cc4a67483bcb9a82e7439d99926)
