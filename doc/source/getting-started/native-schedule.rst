显式配置的原生调度
==================

本例把贝尔电路转换成 L2 原生调度记录，再从 JSON 恢复、认证、投影并关联 L5 输出。
所有时长和资源均为教学用的**合成配置**；4、8、10、6 ns 不代表任何真实设备。
运行结果是测量事件引用，不是采样值；``shot_count`` 只描述实验请求。

配置必须列出实际展开所需的每个有序 ``(kind, qubits)``。虚拟相位操作也需要配置，
时长为零；测量延迟从测量结束时刻起算。这里让两路读出使用各自独占资源。

.. testcode:: native-schedule

   from qaiji import from_qasm3
   from qaiji.core.native import (
       NativeScheduleIR, OperationSpec, QubitResource, ScheduleConfig,
       lower_to_native, qubic_mapping, validate_native_schedule,
   )
   from qaiji.core.program import (
       ExperimentMetadata, ProgramIR, QuantumInvocation, ResultOutput,
       compute_kernel_ref,
   )
   from qaiji.core.program_native import NativeBinding, bridge_program_native

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

``from_json`` 只检查固定格式版本和内部结构；独立认证还需要原始电路和原始配置。
不要根据待认证调度记录的时长反向生成配置。``qubic_mapping`` 和桥接函数
``bridge_program_native`` 会再次认证；先前的 ``report.valid`` 不是可复用的授权令牌。

如果将测量后的 ``Conditional`` 加入电路，条件寄存器的每一位都必须已经测量，
条件区域等待这些位的最新结果就绪；空条件体仍保留区域与屏障。条件只描述寄存器
整体相等比较，不执行真实分支。完整限制见 :doc:`/native-schedule`；字段与异常见
:doc:`/api/native`、:doc:`/api/program_native`。
