<p align="center">
  <img src="logo.png" alt="开济 IR 标识" width="240">
</p>

# 开济IR · Qaiji-IR

[英文](README_EN.md) | **简体中文**

[![Python 3.12–3.14](https://img.shields.io/badge/python-3.12%E2%80%933.14-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![CI](https://github.com/yjmaxpayne/Qaiji-IR/actions/workflows/ci.yml/badge.svg)](https://github.com/yjmaxpayne/Qaiji-IR/actions/workflows/ci.yml)
[![Documentation](https://github.com/yjmaxpayne/Qaiji-IR/actions/workflows/docs.yml/badge.svg)](https://github.com/yjmaxpayne/Qaiji-IR/actions/workflows/docs.yml)
[![Docs](https://img.shields.io/badge/docs-latest-blue)](https://yjmaxpayne.github.io/Qaiji-IR/)
[![codecov](https://codecov.io/gh/yjmaxpayne/Qaiji-IR/graph/badge.svg?token=M9NQqTSx08)](https://codecov.io/gh/yjmaxpayne/Qaiji-IR)
[![OpenQASM 3](https://img.shields.io/badge/OpenQASM-3.0-6929C4)](https://openqasm.com/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23118964.svg)](https://doi.org/10.5281/zenodo.23118964)

> **开济IR · Qaiji-IR** —— 一个跨层的量子-经典**数字孪生**中间表示（IR）。

开济IR · Qaiji-IR 面向混合量子-经典计算，计划以一条跨层 IR 主干承载**语义保持、反馈运行时、
脉冲波形、开放量子系统动力学和校准轨迹**。整体设计横跨八个层级
（`L5 ProgramIR → L0 WaveformIR`，外加侧层 `P DynamicsIR` 与 `T TraceIR`），并以
适配器、目标端或桥接层的身份与 OpenQASM 3、QIR、MLIR 互操作，同时保留自身的语义边界。

## 功能

- **OpenQASM 编解码器**：读取 OpenQASM 2.0 与 3.0（版本头可省略），输出统一规范化为 3.0，
  文本往返保持电路相等。支持 14 个注册门名，另有 19 个标准门名在解析时展开为可序列化门，
  不增加 `GateType`；支持寄存器广播、多个量子寄存器的扁平化和一位经典寄存器的下标条件。
  范围外构件抛出明确的 `QaijiIRError` 子类，不会被静默忽略。展开的等价级别、`cu3` 相位差和
  广播边界见[编解码器文档](doc/source/api/codec.rst)。
- **电路模型与约定**：19 种 `GateType`、不可变的量子/经典节点和可变的 `Circuit` 容器；
  基矢与 RZ 相位约定可执行自检。
- **L4 语义层**（`qaiji.core.semantics`）：把每个操作归入态射类别，提取测量与条件的数据流，
  生成结构身份的 `sha256` 内容哈希，并用 R1–R4 判决引擎判定逐位置结构对应、CNOT/CX 别名折叠
  或整圈旋转折叠是否保持算符语义（`EXACT` 或 `UP_TO_PHASE`）。该层不依赖 OpenQASM 解析器。
- **L5 程序层**（`qaiji.core.program`）：有序的量子调用、实验元数据、结果输出与严格 JSON 往返；
  `compute_kernel_ref` 按固定的 L4 配方生成内核引用，`validate_program` 认证解析表中的电路并
  核对输出寄存器的测量写入，一次报告全部问题。
- **L2 原生调度**（`qaiji.core.native`、`qaiji.core.program_native`）：显式时长与资源配置下的
  CZ 基底展开和确定性调度、严格 JSON 往返，以及独立的来源、规则、矩阵与时序认证；
  `qubic_mapping` 输出中性操作记录，程序桥接按 L5 调用关联测量历史与最终位。Python 构造的
  RX90、RX180、ISWAP、SQISWAP 可参与原生调度，OpenQASM 编解码器不支持这四种门。

可运行教程：[L4 语义摘要](doc/source/getting-started/semantics.rst)、
[L5 程序校验](doc/source/getting-started/program.rst)、
[L2 原生调度](doc/source/getting-started/native-schedule.rst)。

**范围**：本包不执行采样，不提供反馈运行时，不生成 ISA 或波形，也不声明物理保真度；
校准集与设备模型引用只做透传。八层模型中的脉冲（L1）、波形（L0）、动力学（P）与
轨迹（T）层不在本包的公开接口内。

## 安装

```bash
pip install qaiji-ir   # Python 导入名：qaiji
# main 分支上尚未发布的改动：pip install "git+https://github.com/yjmaxpayne/Qaiji-IR.git"
```

Qaiji-IR 支持 Python 3.12–3.14。开发环境的准备见[安装指南](doc/source/getting-started/installation.rst)。

## 快速开始

```python
from qaiji import from_qasm3, to_qasm3

source = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
h q[0];
cx q[0], q[1];
"""

circuit = from_qasm3(source)
canonical = to_qasm3(circuit)
assert from_qasm3(canonical) == circuit
print(canonical)
```

## 文档

在线文档：<https://yjmaxpayne.github.io/Qaiji-IR/>。

本地构建专业中文文档：

```bash
uv sync --group docs && uv run poe docs
```

生成的 HTML 位于 `doc/build/html/`。

## 许可证

Apache-2.0
