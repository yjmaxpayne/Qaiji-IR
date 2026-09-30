故障排查
========

本页用于诊断安装失败、导入错误、OpenQASM 解析、约定自检以及
L5 程序和 L2 原生调度校验问题。
文档构建本身的问题（Sphinx、Make、intersphinx）见 ``doc/README.md``
的故障排查表。

安装与导入问题
--------------

无法导入 ``qaiji``
~~~~~~~~~~~~~~~~~~~

**现象**：``import qaiji`` 报 ``ModuleNotFoundError``。

**排查**：

1. 确认安装的是发布包名 ``qaiji-ir`` 而不是 ``qaiji``：

   .. code-block:: console

      pip list | grep qaiji

   发布包名与导入名不同（``qaiji-ir`` → ``qaiji``），``pip install qaiji``
   不会安装本项目。

2. 确认当前解释器就是安装了依赖的虚拟环境：``source .venv/bin/activate``
   之后重试，或统一使用 ``uv run`` 执行脚本。

3. 开发安装后仍导入失败时，检查安装的是否为可编辑模式且指向本仓库：
   ``uv sync --group tests --group analysis`` 会把 ``src/qaiji`` 以可编辑
   方式接入环境。

Python 版本不满足要求
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**现象**：安装时报 ``requires-python`` 不匹配。

**排查**：Qaiji-IR 要求 Python 3.12–3.14。用 ``python --version`` 确认
当前解释器版本，必要时用 ``uv python install`` 或系统包管理器补齐。

OpenQASM 解析问题
-----------------

解析失败或不支持的构件
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**现象**：``from_qasm3`` 抛出 :class:`qaiji.QaijiIRError` 的子类。

**排查**：

- :class:`qaiji.Qasm3ParseError`：文本有语法错误、不支持的显式版本或嵌套超限。
  输入可以是受支持的 OpenQASM 2/3 文本；缺少版本头本身不再报错。
- :class:`qaiji.Qasm3UnsupportedConstructError`：包含未支持的构件或不合法的
  寄存器用法，例如循环、脉冲语句、``reset``、``barrier``、多位寄存器的单个位条件、
  同名寄存器或 0 qubit 程序。多个量子寄存器已经支持，按声明顺序扁平化。
- :class:`qaiji.Qasm3UnsupportedGateError`：使用了未登记的门或不支持的门修饰符。
  可解析门名是注册表的 14 个加上展开表的 19 个，见 :doc:`/api/codec`；
  不等同于 :class:`qaiji.GateType`。``RX90``、``RX180``、``ISWAP``、``SQISWAP``
  没有本编解码器的映射。

嵌套过深或空输入
~~~~~~~~~~~~~~~~

**现象**：错误含 ``expression nesting exceeds parser limit``，或
``program has no qubit declaration``。

**排查**：前者来自解析或表达式求值等阶段的递归超限；先简化括号和表达式嵌套，
不要依赖提高 Python 递归上限。后者表示没有量子寄存器声明，空、纯空白和纯注释
源码也按这一规则拒收。补上合法的正宽度量子寄存器声明；仅补版本头不能修复空程序。

广播长度不一致
~~~~~~~~~~~~~~

**现象**：错误含 ``broadcast operands have different register sizes``。

**排查**：门广播中的所有整寄存器须等长，包括长度为 1 的寄存器；只有带下标的
单比特操作数可以在门广播中复用。测量的源和目标必须等长；混合整寄存器与下标形式
时，整寄存器一侧必须宽度为 1，不能把一次测量复制到多个位。

寄存器同名
~~~~~~~~~~

**现象**：声明量子或经典寄存器时报重名错误。

**排查**：为所有寄存器使用不同名字，量子与经典寄存器也不能同名。
输出统一的量子寄存器名按 ``q``、``q0``、``q1``、……依次避让经典寄存器名，
因此输出的量子寄存器名字可能与输入不同。

多位寄存器的单个位条件被拒收
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**现象**：``if (c[0] == 1)`` 报
``bit-level condition on a multi-bit register is not supported``。

**排查**：这种下标条件只接受宽度为 1 的经典寄存器，下标必须为 0，比较值只能是
0 或 1。``bit[2] c;`` 上的 ``c[0]`` 条件仍不支持。
已有的整寄存器条件 ``if (c == k)`` 比较完整寄存器的值，与单个位条件含义不同，
不要直接替换而改变程序语义。

cu3 与 Qiskit 的相位不一致
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**排查**：这里的 ``cu3`` 采用官方 OQ2 ``qelib1.inc`` 读法，与 Qiskit 版在控制位
为 1 的子空间上差相对相位 :math:`e^{-i(\varphi+\lambda)/2}`。
这不是整个门的全局相位，不能忽略；核对输入所依据的定义及所需算符，详见
:doc:`/api/codec` 中的等价级别表。

展开后门数变多
~~~~~~~~~~~~~~

**排查**：标准门名在解析阶段展开为已有门，例如 ``ccx`` 变成 15 个门，
``cswap`` 变成 17 个门；广播又会对每组操作数生成完整序列。
输出保留展开后的电路，不恢复原门名。广播没有数量上限，短小的源码也可能生成
大量门；例如宽度为 1000000 的寄存器上执行一次 ``h`` 会产生一百万个门。
先检查寄存器长度和展开规模；不要把源码语句数当作 IR 门数或内存需求。

约定自检失败
------------

**现象**：适配器初始化时调用 :func:`qaiji.core.conventions.self_check`
抛出 :class:`qaiji.ConventionViolationError`。

**排查**：这通常意味着跨边界代码自行推断或复制了基矢/相位映射。约定必须
从 :mod:`qaiji.core.conventions` 导入权威常量，而不是本地重写一份；映射
语义见 :doc:`/conventions`。不要捕获该异常继续运行——静默的基矢翻转是
单比特门保真度的致命错误。

程序引用或结果输出校验失败
--------------------------

**现象**：:func:`qaiji.core.program.validate_program` 抛出
:class:`qaiji.core.program.ProgramValidationError`。

**排查**：读取异常的 ``problems`` 元组。``kernel_ref`` 缺失时检查解析表是否包含
该引用；出现 ``re-hashes to`` 时，用当前电路重新计算引用并更新程序和解析表。
输出错误则检查寄存器名、调用索引，以及该寄存器每一位是否被测量写入。
程序 JSON 仅保存引用，不附带电路；校准和设备引用不参与该校验。
完整示例见 :doc:`program`。

原生调度输入与认证失败
----------------------

**现象**：原生调度入口抛出 ``NativeInputError``、``NativeValidationError``，
或 ``bridge_program_native`` 抛出 ``ProgramNativeValidationError``。

**排查**：输入错误先查看 ``code`` 和 ``path``，确认配置为每个实际使用的有序
``(kind, qubits)`` 提供规格，资源和时长符合约束。认证失败查看报告各层的
``issues``：来源、展开规则、矩阵关系和时序分别检查。桥接错误先排除
``ProgramValidationError``，再按调用索引检查绑定及其原始电路、调度记录和配置。
``from_json`` 成功仅表示 JSON 结构可恢复，不能替代
``validate_native_schedule(circuit, schedule, config)``。限制和示例见
:doc:`/native-schedule`、:doc:`native-schedule`。
