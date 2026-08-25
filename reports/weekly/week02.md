# Week 2 Report

## 本周目标

逐层验证 Coin-X5 的基础仿真、机器人、资产、控制和评分链路，将失败收敛为可独立验证的根因候选。

## 完成情况

- [x] 验证最小仿真环境、物理步进和三路渲染
- [x] 建立 dual-X5 关节与 14 维 action 的对应表
- [x] 验证单关节响应、夹爪尺度和左右臂语义
- [x] 核对 coin、stand、piggy bank 的资产和坐标链
- [x] 完成三次低速受控碰撞探针
- [x] 逐层追踪 ACT action 到实际 joint position
- [x] 保存固定 seed/layout 的 300 步完整失败轨迹
- [x] 审计本地 dirty diff、官方版本和 checkpoint 兼容性
- [x] 形成三项单变量、可证伪的 Week 3 实验计划

## 核心结果

- 无 ACT 时环境可稳定 reset 和步进，硬币静置最大位移仅 `8.47e-7 m`。
- 三路 RGB 均为有效的 `480 x 640 x 3` 图像，未发现空帧、恒定帧或明显视野异常。
- ACT 的 14 维动作顺序和左右臂语义正确；单关节探针和正式控制链均未发现维度错位或静默丢失。
- 夹爪归一化、物理尺度、10 个内部控制 target、队列写入和实际关节响应均可追踪。
- 完整基线轨迹达到 `300/300` policy steps 和 `3000/3000` internal records，无缺步和无效数值。
- 基线最终为 `success=false`、`score=0.0`，硬币最大抬升仅 `1.79e-7 m`；最早失败点仍是夹爪闭合后、coin lift 前。
- policy step 151 的 chunk 边界出现约 `0.7958 rad` 最大 tracking error，提示时序风险，但尚不能单独解释首个 chunk 内的抓取失败。
- 官方差异审计识别出三项优先候选：RGB/BGR 通道、temporal aggregation 和 stand collision。

## 已排除层级

- 安装或 Isaac Sim 无法启动；
- 场景、机器人、硬币或三路相机未加载；
- 策略服务无响应或策略完全无动作；
- 14 维动作静态错位、左右交换或控制队列丢失；
- 机器人关节完全不响应；
- reward 使用错误 coin 实例或不同坐标系；
- 单纯的 success condition 漏触发。

“已排除”仅指现有证据不支持其作为主要失败层级，不表示所有视觉语义和接触物理都已验证正确。

## 当前根因候选

1. **H1 RGB/BGR：高风险。** 本地 runtime adapter 无条件转换通道，而官方契约和训练数据更支持 RGB。
2. **H2 Temporal aggregation：高风险。** 本地关闭官方聚合模式，chunk 边界已有明显 tracking 瞬态。
3. **H3 Stand collision：中风险。** 本地 stand 使用 triangle-mesh collision，可能改变硬币受约束和脱离过程。

三项假设的支持、反对、缺失证据及预注册门槛见 [Day 7 根因实验计划](../../simulation/robodojo/validation/week02_day07_root_cause_plan.md)。

## 本周产物

- [Day 1 仿真与渲染验证](../../simulation/robodojo/validation/week02_day01_sim_render.md)
- [Day 2 机器人模型与关节验证](../../simulation/robodojo/validation/week02_day02_robot_model.md)
- [Day 3 资产、碰撞体与坐标验证](../../simulation/robodojo/validation/week02_day03_assets_coordinates.md)
- [Day 4 动作控制链验证](../../simulation/robodojo/validation/week02_day04_action_control.md)
- [Day 5 固定种子完整轨迹](../../simulation/robodojo/validation/week02_day05_full_trajectory.md)
- [Day 6 官方基线与版本审计](../../simulation/robodojo/validation/week02_day06_upstream_comparison.md)
- [Day 7 根因假设与实验卡](../../simulation/robodojo/validation/week02_day07_root_cause_plan.md)
- [Coin-X5 故障诊断入口](../../simulation/robodojo/troubleshooting/coin_x5.md)

## 风险

- 尚未得到成功轨迹，多个根因可能同时存在。
- 正式 ACT 基线目前只有一次完整运行，固定 seed 不等于 GPU 仿真逐位确定。
- 基线没有可靠 contact force，因此不能仅凭视频认定物理接触。
- RoboDojo 和子模块仍有本地修改；实验必须保存精确 patch 和环境变量。
- checkpoint 缺少训练 commit、颜色通道和 layout manifest，版本同源性仍不能完全确认。
- H2 的本地 temporal buffer 初始化存在实现前置风险，必须先做 synthetic 验证。

## 下周三个重点

1. Week 3 Day 1：执行 RGB/BGR 配对实验 E1。
2. Week 3 Day 2：验证 temporal buffer 后执行 temporal aggregation 配对实验 E2。
3. Week 3 Day 3：冻结 scripted/专家轨迹，只改变 stand collision，执行 E3。

每项实验至少完成 3 组匹配 A/B；结果分裂时扩展到 5 组。一次仍然失败不会被写成证伪，判断依据是预先定义的抓取几何、轨迹连续性、coin 位移和成功指标。

## 周状态

**Green**

Week 2 已完成最小复现、逐层验证、完整轨迹、官方差异审计和三条可执行根因路线。Coin-X5 尚未成功不影响本周验收；当前问题已从整体失败收敛为 Week 3 可逐项对照的实验变量。
