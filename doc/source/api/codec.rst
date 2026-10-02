OpenQASM 3 编解码器
===================

编解码器把受支持的 OpenQASM 2/3 文本转换为电路级 IR，并把可序列化电路统一
输出为 OpenQASM 3.0。它接受门名展开、寄存器广播和一位经典寄存器的条件；
未支持的构件通过具有明确类型的异常拒绝。文本往返保持解析后的电路，
不保留源码的寄存器划分、门名或排版。

.. autoclass:: qaiji.codec.GateSpec
   :members:

.. autofunction:: qaiji.from_qasm3

.. autofunction:: qaiji.to_qasm3

元数据出口
----------

需要把电路中的操作对应回源码时，使用 ``qaiji.codec.parse_qasm3``。它只解析一次，
同时返回电路和逐操作的源码来历；接受与拒收的源码和 ``from_qasm3`` 完全相同。

* ``origins`` 与 ``circuit.gates`` 逐位一一对应。广播或门名展开产生的多个操作共享
  所属语句的 span，用 ``broadcast_index`` 和 ``expansion_index`` 区分；条件操作的
  origin 用 ``body`` 按同样规则对应条件体内的门。``statement_index`` 是顶层语句序号，
  声明等不产生操作的语句也占号，条件体内的门沿用所属 ``if`` 的序号。
* 行号和列号都从 1 起，``line:column`` 到 ``end_line:end_column`` 为闭区间；列按
  Unicode code point 计，与错误消息中的 ``at line:column`` 采用同一约定。
* origin 只是旁表：电路的 ``==``、语义摘要哈希、``canonicalize()`` 和 ``to_qasm3``
  都不读取它。``ParsedQasm3`` 本身不可哈希，它的 ``==`` 同时比较电路和 origins；
  只比较语义时请比较 ``.circuit``。
* ``circuit`` 仍是可变容器。调用方增删或替换其中的操作后，``origins`` 不再对齐，
  记录不做运行期检查。
* ``declared_version`` 是版本头原文，例如 ``"3.0"``；缺少版本头时为 ``None``，
  此时 ``version_header_present`` 为 ``False``。

下面的 ``CY`` 展开为 3 个门，3 条 origin 都保留源码拼写和同一 span：

.. doctest::

   >>> from qaiji.codec import parse_qasm3
   >>> parsed = parse_qasm3("qubit[2] q; h q[0];\nCY q[0], q[1];")
   >>> len(parsed.origins) == len(parsed.circuit.gates)
   True
   >>> [(o.raw_name, o.line, o.expansion_index) for o in parsed.origins]
   [('h', 1, 0), ('CY', 2, 0), ('CY', 2, 1), ('CY', 2, 2)]
   >>> parsed.version_header_present
   False

.. autofunction:: qaiji.codec.parse_qasm3

.. autoclass:: qaiji.codec.ParsedQasm3
   :members:

.. autoclass:: qaiji.codec.OperationOrigin

支持边界
--------

注册表支持 ``id``、``x``、``y``、``z``、``h``、``s``、``t``、``rx``、
``ry``、``rz``、``u3``、``cx``、``cz`` 和 ``swap``，共 14 个门名。
另有下表的 19 个门名在解析时展开为这些可序列化门；展开不增加
:class:`~qaiji.GateType`，也不影响 IR 格式版本。门名查找沿用
``.lower()``，因此这些门名的大写变体也可接受；寄存器名仍区分大小写。
IR 中的 ``CNOT`` 在输出时规范化为 ``cx``。
``RX90``、``RX180``、``ISWAP`` 与 ``SQISWAP`` 属于电路模型，
但没有本编解码器的门映射，``to_qasm3`` 会拒绝包含这些门的电路。需要这些门时可从
Python 构造电路并使用 :doc:`native` 中的原生调度生成接口；它输出的是
``NativeScheduleIR``，不是可交回 ``to_qasm3`` 的电路。

版本头、寄存器与错误收敛
~~~~~~~~~~~~~~~~~~~~~~~~

* 缺少 ``OPENQASM`` 版本头的文本可以接受；显式版本的主号只接受 2 或 3，
  畸形版本和其他主号拒收。
* 多个量子寄存器按声明顺序连续映射到同一电路的比特编号。
* 量子寄存器与经典寄存器同名时拒收，无论谁先声明；同类寄存器重名也拒收。
* 宽度为 1 的经典寄存器上的 ``if (c[0] == 0)`` 或 ``if (c[0] == 1)`` 降为整个寄存器的
  ``Conditional``；下标必须为整数字面量且不越界。
* 解析或表达式求值中的递归超限抛出 :class:`~qaiji.Qasm3ParseError`，
  detail 为 ``expression nesting exceeds parser limit``。
* 空、纯空白或纯注释源码按“没有 qubit 声明”拒收，抛出
  :class:`~qaiji.Qasm3UnsupportedConstructError`，detail 为
  ``program has no qubit declaration``；解析库调用中的其他 ``AttributeError``
  包装为 :class:`~qaiji.Qasm3ParseError`。
* 超出解释器整数字符串转换上限（默认 4300 位，见 :func:`sys.set_int_max_str_digits`）
  的十进制整数字面量抛出 :class:`~qaiji.Qasm3ParseError`，消息为 ``source at 1:1:``
  加解释器原生消息，原异常保留为 ``__cause__``。
* 门参数中未超出位数上限、但超出浮点范围的整数按无穷大求值，由既有的有限性检查
  拒收：抛出 :class:`~qaiji.Qasm3UnsupportedConstructError`，detail 为
  ``Gate parameters must be finite``。``1/N`` 下溢为 ``0.0`` 并被接受；``1/(1/N)``
  抛出 :class:`~qaiji.Qasm3ParseError`，detail 为 ``division by zero``；``N**2`` 与
  ``N%2`` 与小操作数时一样报 ``unsupported binary expression``。
* 十六进制、二进制、八进制字面量（寄存器宽度、下标、条件值、参数）以及累计的
  qubit 总数同样受该上限约束；超限时抛出 :class:`~qaiji.Qasm3ParseError`，消息为
  ``<构件> at 行:列:`` 加解释器原生消息。位置指向该字面量，宽度指向 ``[``；
  总数越限时指向使总数越限的那条声明。经典位总数不设上限。
* 输出的量子寄存器名依次尝试 ``q``、``q0``、``q1``、……，选择首个未被
  经典寄存器占用的名字。

这些规则在各版本之间的变化记录在仓库根目录的 ``CHANGELOG.md``。

广播、寄存器与条件
~~~~~~~~~~~~~~~~~~

门广播要求所有整寄存器操作数长度相同；带下标的单比特操作数在各次广播中复用。
长度为 1 的整寄存器仍参与长度比较，不会当作单比特自动扩展。
例如 ``cx a[0], b;`` 可将一个比特与 ``b`` 中各比特配对，而宽度为 1 的 ``a``
和宽度为 2 的 ``b`` 不能用于 ``cx a, b;``。每组操作数仍须满足门元数、
比特不重复和范围检查。广播展开按下标逐段完成：先生成第 0 组的完整门序列，
再生成第 1 组，依此类推。

测量要求源和目标长度相等，不复用单个源比特或目标位。整寄存器与带下标操作数
混用时，整寄存器一侧必须宽度为 1。例如宽度为 1 的 ``q`` 可以用于
``c[0] = measure q;``，宽度为 1 的 ``c`` 可以用于 ``c = measure q[0];``。
两侧都是整寄存器时，按对应下标测量；OpenQASM 2 的箭头形式遵循相同规则。

多量子寄存器在输出时统一为一个量子寄存器。下面的无头输入同时展示广播、
门名展开与命名避让：

.. doctest::

   >>> from qaiji import from_qasm3, to_qasm3
   >>> circuit = from_qasm3("qubit[2] a; qubit b; bit q; sx a; cx a[0], b;")
   >>> circuit.num_qubits, len(circuit)
   (3, 3)
   >>> [gate.qubits for gate in circuit.gates]
   [(0,), (1,), (0, 2)]
   >>> emitted = to_qasm3(circuit)
   >>> "qubit[3] q0;" in emitted
   True
   >>> from_qasm3(emitted) == circuit
   True

支持整寄存器相等条件 ``if (c == k)``；多位寄存器的单个位条件
``if (c[0] == 1)`` 会被拒收。条件体只支持门语句，不支持 ``else``。
没有 qubit 声明或 0 qubit 的程序会被拒收。参数表达式中的 ``**`` 和 ``%``
会被拒收，不做求值；循环、``reset``、``barrier``、脉冲语句及自定义门定义不受支持。完整错误分类见 :doc:`exceptions`。

广播没有设置数量上限：22 字节的 ``qubit[1000000] q; h q;``
会生成 :math:`10^6` 个门。展开会实际分配这些门，
所需时间和内存随展开规模增长；调用方应根据可用资源控制输入中的寄存器长度。

19 个门名的展开等价级别
~~~~~~~~~~~~~~~~~~~~~~~

表中 R3 指 OpenQASM 3 ``stdgates.inc`` 参考，R2 指官方 OpenQASM 2
``qelib1.inc`` 参考。``EXACT`` 表示算符严格相等；“相位”表示只差一个整体全局相位，
对多比特门是整个酉矩阵共同的相位，不是受控子空间之间的相对相位。
“—”表示不对该参考作声明。``u`` 的 R2 参考取 OpenQASM 2 内置 ``U``；
``u``、``cswap`` 都不在官方 OQ2 ``qelib1.inc`` 中。

.. list-table:: 标准门名展开
   :header-rows: 1

   * - 名字
     - 对 R3
     - 对 R2
   * - ``p``
     - EXACT
     - —
   * - ``u1``
     - EXACT
     - 相位
   * - ``u2``
     - 相位
     - 相位
   * - ``u``
     - —
     - 相位
   * - ``sdg``
     - EXACT
     - 相位
   * - ``tdg``
     - EXACT
     - 相位
   * - ``sx``
     - 相位
     - —
   * - ``sxdg``
     - 相位
     - —
   * - ``cy``
     - EXACT
     - EXACT
   * - ``ch``
     - EXACT
     - 相位
   * - ``crx``
     - EXACT
     - —
   * - ``cry``
     - EXACT
     - —
   * - ``crz``
     - EXACT
     - EXACT
   * - ``cp``
     - EXACT
     - —
   * - ``cu1``
     - —
     - 相位
   * - ``cu``
     - EXACT
     - —
   * - ``cu3``
     - —
     - EXACT
   * - ``ccx``
     - EXACT
     - 相位
   * - ``cswap``
     - EXACT
     - —

``cu3`` 采用官方 OQ2 原文的读法。与 Qiskit 版 ``qelib1`` 的读法相比，
控制位为 1 的子空间多一个相对相位 :math:`e^{-i(\varphi+\lambda)/2}`；
它不能作为整个两比特门的全局相位忽略。迁移 Qiskit 语料时须核对所用定义。
展开后的 IR 不保留原门名；单比特名字展开为 1 个门，多比特名字展开为 3–17 个门，
例如 ``cy`` 为 3 个、``ccx`` 为 15 个、``cswap`` 为 17 个。
