# 环境信息记录（RoboDojo 评估机）

> 记录日期：2026-08-13

## 主机 / 系统

| 项目 | 值 |
| :-- | :-- |
| 系统 | Ubuntu 24.04.4 LTS (Noble Numbat) |
| 内核 | Linux 6.17.0-40-generic (x86_64) |
| 硬件 | ASUS TUF GAMING Z790-PLUS WIFI（固件 1805，2024-10-30） |
| 主机名 | nvidia-System-Product-Name |

## GPU / 驱动

| 项目 | 值 |
| :-- | :-- |
| 驱动版本 | 570.211.01 |
| 驱动支持的最高 CUDA | 12.8 |
| GPU | NVIDIA GeForce RTX 5070，显存 12227 MiB（约 12 GB） |
| 当前显存占用 | 1173 MiB（GPU-Util 4%，温度 45°C） |

## CUDA

| 项目 | 值 |
| :-- | :-- |
| `nvcc` | release 12.0, V12.0.140（路径 `/usr/bin/nvcc`） |

> ⚠️ 注意：驱动最高支持 CUDA 12.8，但系统安装的 `nvcc` 工具链是 **12.0**，存在版本差（不影响运行时，PyTorch 自带 CUDA 12.8 运行时）。

## Python

| 项目 | 值 |
| :-- | :-- |
| 系统 `python3` | 3.12.3（`/usr/bin/python3`，无 `python` 命令） |
| conda | `/home/nvidia/miniconda3`（`base`） |

Conda 环境（均为 **Python 3.11.15**）：

| 环境 | 用途 |
| :-- | :-- |
| `RoboDojo` | 主评估环境（本项目的核心依赖） |
| `isaacsim` | 独立的 Isaac Sim / IsaacLab 环境 |
| `act` | ACT 训练环境 |

## 项目依赖版本

### 环境 `RoboDojo`（主评估环境）

| 包 | 版本 |
| :-- | :-- |
| isaacsim | 5.1.0.0 |
| isaaclab | 0.54.3（editable，来自 `third_party/IsaacLab` 子模块） |
| isaaclab_assets | 0.2.4 |
| isaaclab_mimic | 1.0.16 |
| isaaclab_rl | 0.5.0 |
| isaaclab_tasks | 0.11.14 |
| torch | 2.7.0+cu128 |
| numpy | 1.26.0 |
| scipy | 1.15.3 |
| gymnasium | 1.2.1 |
| einops | 0.8.2 |
| websockets | 16.1.1 |
| msgpack / msgpack-numpy | 1.2.1 / 0.4.8 |
| huggingface_hub | 0.36.2 |

### 环境 `isaacsim`（备选）

- isaacsim 5.1.0.0，但 isaaclab 为 **2.3.2.post1**（pip 安装，与主环境的 0.54.3 不同）
- torch 2.7.0+cu128 / numpy 1.26.0 / gymnasium 1.2.0 / websockets 12.0

### 环境 `act`

- torch 2.7.0+cu128 / numpy 2.4.4 / scipy 1.17.1 / einops 0.8.2

### 仓库声明依赖

- `pyproject.toml`：项目名 `robodojo` v0.2.0，`requires-python = ">=3.11"`
- `scripts/requirements.txt`：huggingface_hub、transforms3d、ffmpeg、open3d、msgpack-numpy、ruff≥0.11.7、pre-commit≥4.2.0
- `XPolicyLab/pyproject.toml`：numpy≥1.23、pyyaml≥6、opencv-python-headless≥4.8、h5py≥3.8、websockets≥13、msgpack≥1.0.8、msgpack-numpy≥0.4.8、pydantic≥2.5

## 子模块

| 子模块 | 分支 | 状态 |
| :-- | :-- | :-- |
| XPolicyLab | main | `+`（有未提交改动） |
| third_party/IsaacLab | main | 干净 |
| third_party/curobo | main | `+`（有未提交改动） |

> 补充说明：`curobo` 未作为 pip 包安装在 `RoboDojo` 环境里（是 git 子模块，可能走源码路径导入）。`XPolicyLab` 与 `third_party/curobo` 两个子模块当前都有未提交改动（gitlink 前有 `+`）。
