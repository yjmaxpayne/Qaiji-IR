<p align="center">
  <img src="logo.png" alt="开济 IR 标识" width="240">
</p>

# 开济IR · Qaiji-IR

[英文](README_EN.md) | **简体中文**

> **开济IR · Qaiji-IR** —— 一个跨层的量子-经典**数字孪生**中间表示（IR）。

开济IR · Qaiji-IR 面向混合量子-经典计算，计划以一条跨层 IR 主干承载**语义保持、反馈运行时、
脉冲波形、开放量子系统动力学和校准轨迹**。整体设计横跨八个层级
（`L5 ProgramIR → L0 WaveformIR`，外加侧层 `P DynamicsIR` 与 `T TraceIR`），并以
适配器、目标端或桥接层的身份与 OpenQASM 3、QIR、MLIR 互操作，同时保留自身的语义边界。

## 当前状态

八层模型是项目的整体方向。当前已交付的 Slice A 聚焦电路级前端，包含 19 种 `GateType` 门类型、
不可变的量子/经典节点、OpenQASM 3 双向编解码器、黄金往返契约，以及可执行的基矢与
RZ 相位约定自检。OpenQASM 2.0 可作为兼容输入读取，输出统一规范化为 3.0；范围外构件会
抛出明确的 `QaijiIRError` 子类，不会被静默忽略。 M-1 进一步支持无版本头输入、多量子
寄存器扁平化、寄存器广播和一位经典寄存器的下标条件。编解码器在 14 个注册表门名之外
新增 19 个门名的解析期展开；这与上述 19 种 `GateType` 是两个不同集合，门类型枚举未变。
展开的等价级别、`cu3` 相位差和广播边界见[编解码器文档](doc/source/api/codec.rst)。

在电路前端之上，`qaiji.core.semantics` 交付了 L4 语义授权层：把每个操作归入
态射类别、提取测量与条件的数据流、生成结构身份的 `sha256` 内容哈希，
以及一套 R1–R4 保语义判决引擎（判定逐位置结构对应、CNOT/CX 别名折叠或整圈旋转是否仍保持
算符语义，达到 `EXACT` 或 `UP_TO_PHASE` 精度）。该层不导入 OpenQASM 解析依赖，由
两项导入纯度测试守护。作为该层判决引擎的判定域前置基础，`Gate.canonicalize()`
的整圈旋转折叠判据同时收紧为对任意 `2*pi*k` 整倍角度精确折叠（此前在超大角度下
可能因取模残差超出容差而漏折）。

`qaiji.core.program` 提供 L5 程序描述：有序的量子调用、实验元数据、结果输出和
严格 JSON 往返。`compute_kernel_ref` 按固定 L4 配方生成引用；`validate_program`
认证解析表中的电路并核对输出寄存器的完整测量写入，一次报告全部问题。
校准集与设备模型引用仅透传；实际采样和反馈运行时尚未实现。
[L4 可运行教程](doc/source/getting-started/semantics.rst)与
[L5 可运行教程](doc/source/getting-started/program.rst)分别展示摘要判决与程序校验。

`qaiji.core.native` 提供显式时长/资源配置的 CZ 基底展开、确定性 L2 调度、严格 JSON
往返及独立来源/规则/矩阵/时序认证。`qubic_mapping` 输出中性操作记录；
`qaiji.core.program_native` 按 L5 调用关联测量历史与最终位引用。
[可运行教程](doc/source/getting-started/native-schedule.rst) 使用合成配置；这些能力
不生成 ISA 或波形，不执行实际采样，也不声明物理保真度。Python 构造的四种门
RX90、RX180、ISWAP、SQISWAP 可参与原生调度生成，原 OpenQASM 编解码器仍拒收这四种门。

## 安装

```bash
pip install qaiji-ir      # Python 导入名：qaiji
```

包尚未发布到 PyPI；在首个发布之前，请在克隆仓库后使用 `pip install .` 安装。

Qaiji-IR 支持 Python 3.12–3.14。

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

本地构建专业中文文档：

```bash
uv sync --group docs && uv run poe docs
```

生成的 HTML 位于 `doc/build/html/`。当前切片只保证本地可复现构建，尚未配置
Read the Docs 或 GitHub Pages 发布。

## 许可证

Apache-2.0
