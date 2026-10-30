L2 原生调度：生成、认证与桥接
==============================

本页先把贝尔电路转换为 L2 原生调度记录，再依次从 JSON 恢复、认证和投影；
最后一节把测量事件关联到 L5 程序的输出。前置页：:doc:`quickstart`。

调度、认证与投影
----------------

所有时长和资源都是教学用的\ **合成配置**\ ；4、8、10、6 ns 不代表任何真实设备。

配置必须为展开结果中出现的每个有序 ``(kind, qubits)`` 给出规格。虚拟相位操作也需要规格，
时长为零。测量的结果延迟从测量结束时刻起算。本例中两路读出各用一个独占资源。

.. testcode:: native-schedule

   from qaiji import from_qasm3
   from qaiji.core.native import (
       NativeScheduleIR, OperationSpec, QubitResource, ScheduleConfig,
       lower_to_native, qubic_mapping, validate_native_schedule,
   )

   circuit = from_qasm3("""OPENQASM 3.0;
   include "stdgates.inc";
   qubit[2] q;
   bit[2] c;
   h q[0];
   cx q[0], q[1];
   c[0] = measure q[0];
   c[1] = measure q[1];
   """)
   config = ScheduleConfig(
       qubit_resources=(
           QubitResource(qubit=0, resource="q0"),
           QubitResource(qubit=1, resource="q1"),
       ),
       operation_specs=(
           OperationSpec(kind="RZ", qubits=(0,), duration_ns=0,
                         resources=("q0",), result_latency_ns=0),
           OperationSpec(kind="RX90", qubits=(0,), duration_ns=4,
                         resources=("q0",), result_latency_ns=0),
           OperationSpec(kind="RZ", qubits=(1,), duration_ns=0,
                         resources=("q1",), result_latency_ns=0),
           OperationSpec(kind="RX90", qubits=(1,), duration_ns=4,
                         resources=("q1",), result_latency_ns=0),
           OperationSpec(kind="CZ", qubits=(0, 1), duration_ns=8,
                         resources=("q0", "q1"), result_latency_ns=0),
           OperationSpec(kind="MEASURE", qubits=(0,), duration_ns=10,
                         resources=("q0",), result_latency_ns=6),
           OperationSpec(kind="MEASURE", qubits=(1,), duration_ns=10,
                         resources=("q1",), result_latency_ns=6),
       ),
       cz_couplings=((0, 1),),
   )
   schedule = lower_to_native(circuit, config)
   restored = NativeScheduleIR.from_json(schedule.to_json())
   assert restored == schedule
   report = validate_native_schedule(circuit, restored, config)
   assert report.valid
   assert restored.end_ns == 40
   assert report.all_results_ready_ns == 46
   projection = qubic_mapping(circuit, restored, config)
   assert projection.events == restored.events
   assert projection.all_results_ready_ns == max(e.ready_ns for e in restored.events)

``from_json`` 只检查固定的格式版本和记录的内部结构。独立认证还需要原始电路和原始配置。
不要用待认证调度记录中的时长反向生成配置。``qubic_mapping`` 每次调用都重新认证；
之前得到的 ``report.valid`` 不能代替这次认证。下一节的 ``bridge_program_native`` 也一样。

电路在测量之后含 ``Conditional`` 时，条件寄存器的每一位都必须已经测量过。
条件区域在这些位的最新结果就绪之后才开始。条件体为空时，调度仍保留该区域及其屏障。
条件只描述整个寄存器的相等比较，不执行真实分支。

关联 L5 输出
------------

本节使用 L5 程序记录。``ProgramIR`` 与 ``kernel_ref`` 的含义见 :doc:`program`；
初次阅读时可以先跳过本节，读完 :doc:`program` 之后再回来。
下面的代码沿用上一节的 ``circuit``、``restored`` 与 ``config``。

.. testcode:: native-schedule

   from qaiji.core.program import (
       ExperimentMetadata, ProgramIR, QuantumInvocation, ResultOutput,
       compute_kernel_ref,
   )
   from qaiji.core.program_native import NativeBinding, bridge_program_native

   kernel_ref = compute_kernel_ref(circuit)
   program = ProgramIR(
       quantum_invocations=(QuantumInvocation(kernel_ref),),
       experiment_metadata=ExperimentMetadata(shot_count=100),
       result_outputs=(ResultOutput(0, "c"),),
   )
   mapping = bridge_program_native(
       program, {kernel_ref: circuit},
       {0: NativeBinding(schedule=restored, config=config)},
   )
   output = mapping.outputs[0]
   assert [(e.invocation_index, e.event_id) for e in output.history] == [
       (0, "m0"), (0, "m1"),
   ]
   assert [(b.bit_index, b.event.event_id) for b in output.final_bits] == [
       (0, "m0"), (1, "m1"),
   ]

``bridge_program_native`` 先校验 L5 程序，再认证每个调用绑定的 L2 调度，
最后为每个结果输出列出测量事件的历史和每位最后一次测量。
这些输出是测量事件的引用，不是采样值；``shot_count`` 只描述实验请求。

相关页面：完整限制见 :doc:`/core-concepts/native-schedule`；字段与异常见
:doc:`/api/native`、:doc:`/api/program_native`。

下一步：:doc:`semantics` 说明 L4 摘要、内容哈希与保持性判决。L3 的条件依赖记录在 L4 摘要中，
也在该页说明。
