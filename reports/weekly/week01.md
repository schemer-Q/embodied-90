# Week 1 Report

> 周期：2026-08-12 至 2026-08-18
> 状态：Green

## 本周目标

将 Coin-X5 失败状态转化为可重复、可分析的问题，并冻结支持后续复现的代码与环境证据。

## 完成情况

- [x] 建立并同步 GitHub 仓库
- [x] 记录主机和 RoboDojo 环境
- [x] 完成 Coin-X5 最小运行并保存日志
- [x] 使用现有 ACT 权重完成正式单 episode 复评
- [x] 完成失败层级分类
- [x] 追踪策略、动作控制、仿真和评分执行链路
- [x] 建立统一故障诊断入口
- [x] 归档 RoboDojo、XPolicyLab 和 cuRobo 状态

## 核心结果

- CUDA 和 Isaac Sim 可用，机器人、硬币与场景成功创建。
- ACT policy server 建立 WebSocket 连接并持续输出非零 14-D action。
- dual-X5 关节和夹爪实际响应，说明动作已进入控制链路；这不等价于动作语义已经验证正确。
- episode 完成 300/300 policy steps，正式结果为 `success=false`、`score=0.0`。
- 左夹爪约在 policy step 34 闭合到 `0.01` 以下，硬币仍未抬升超过初始高度 `0.08 m`。
- 最早确认失败点位于夹爪闭合后、硬币 lift 前，评分第二阶段尚未进入。

证据与边界见 [Coin-X5 Troubleshooting](../../simulation/robodojo/troubleshooting/coin_x5.md)。

## 已排除或暂不支持

- 安装失败。
- 仿真无法启动或无法完成 episode。
- 机器人、硬币或场景关键资源完全缺失。
- Policy server 无响应。
- 策略完全没有动作。
- 机械臂完全不响应。
- 单纯的 success condition 漏触发作为唯一原因：`score=0.0` 表明 lift 阶段未完成。

这些结论只排除链路完全失效，不代表动作映射、控制时序或物理参数正确。

## 当前未决问题

- H1：夹爪闭合时是否正确对准硬币。
- H2：夹爪闭合时机或 ACT chunk 时序是否适合当前状态。
- H3：动作维度、左右臂语义或关节映射是否存在偏差。
- H4：硬币碰撞、摩擦或抓取物理参数是否异常。

对应的 E1-E5 可证伪实验已按低成本到高侵入性排序记录在 [故障诊断入口](../../simulation/robodojo/troubleshooting/coin_x5.md#7-可证伪实验)。

## 本周产物

| 产物 | 链接 | 用途 |
| --- | --- | --- |
| 主机环境记录 | [environment.md](../../environment.md) | Day 2 主机、CUDA、Python 和核心依赖 |
| Week 1 环境快照 | [snapshot](../../environment/snapshots/week01/README.md) | commit、submodule、pip freeze、status 和 dirty patches |
| Day 3 最小运行命令 | [coin_x5_minimal.sh](../../simulation/robodojo/commands/coin_x5_minimal.sh) | 可复查的启动命令 |
| Day 3 运行日志 | [coin_x5_day03.log](../../simulation/robodojo/logs/coin_x5_day03.log) | 环境、资源和仿真启动证据，不作为 ACT 行为基线 |
| Day 4 正式评测日志 | [eval](../../simulation/robodojo/logs/coin_x5_day04_act_eval_clean.log) | ACT 单 episode 评测结果 |
| ACT 动作日志 | [prediction](../../simulation/robodojo/logs/coin_x5_day04_act_pred.log) / [execution](../../simulation/robodojo/logs/coin_x5_day04_act_exec.log) | 策略输出和关节响应证据 |
| Day 4 故障分类 | [day04_failure_classification.md](../../simulation/robodojo/troubleshooting/day04_failure_classification.md) | 失败层级与最早断点 |
| Day 5 执行流程 | [coin_x5_execution_flow.md](../../simulation/robodojo/docs/coin_x5_execution_flow.md) | CLI 到 reward/success 的代码链路 |
| Day 6 诊断入口 | [coin_x5.md](../../simulation/robodojo/troubleshooting/coin_x5.md) | 已排除项、假设和实验导航 |
| ACT 三路关键帧 | [head](../../simulation/robodojo/troubleshooting/day04_frames/act_head_sheet.jpg) / [left wrist](../../simulation/robodojo/troubleshooting/day04_frames/act_left_wrist_sheet.jpg) / [right wrist](../../simulation/robodojo/troubleshooting/day04_frames/act_right_wrist_sheet.jpg) | 行为阶段的视觉证据 |

## 环境快照

- RoboDojo：`9226f48ea694b3f53db12d4922e8b1199f8d0891`，dirty。
- XPolicyLab：`3e6b42cda67ad6c02aaef2fec16815490c328751`，dirty，修改已单独导出 patch。
- IsaacLab：`afca7b09d60d8beb9c1cb28b43066499940b969b`。
- cuRobo：`895c6517243f8cb091c73c018c8167192d39599a`；工作树 patch 为空，主仓库记录的 gitlink 与当前 checkout 不同。
- RoboDojo 环境：Python `3.11.15`；完整依赖见 [pip_freeze.txt](../../environment/snapshots/week01/pip_freeze.txt)。

三份 patch 已扫描 Token、密码、账号信息、带凭据 URL 和本机绝对路径，未发现敏感信息。未跟踪安装包、下载物和临时日志未归档，完整路径清单保存在 [robodojo_status.txt](../../environment/snapshots/week01/robodojo_status.txt)。

## 风险

- RoboDojo 和 XPolicyLab 仍有未提交修改；快照可恢复 tracked diff，但未归档全部 untracked 文件。
- 当前只有一个正式 episode，不能估计成功率分布或随机性影响。
- 尚未获得成功轨迹，无法完成成功/失败逐阶段对照。
- Day 5 代码行号依赖当前本地工作树，后续代码变化可能使行号失效。
- 当前证据尚未区分策略对准/时序、动作语义和物理交互问题。

## 下周三个重点

1. 验证最小仿真环境和渲染，建立不依赖任务策略的基础健康检查。
2. 检查 dual-X5 模型、关节顺序、动作范围和初始状态。
3. 验证硬币资产、碰撞体、摩擦参数和坐标系。

## 周状态

**Green**

Week 1 核心交付已完成：失败可稳定复现，环境和工作树已归档，执行链与评分边界有代码证据，未决根因已转换为相互可区分的实验。当前风险不会阻止 Week 2 进入场景、机器人和控制链的逐层验证。
