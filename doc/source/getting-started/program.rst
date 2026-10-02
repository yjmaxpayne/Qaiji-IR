L5 程序引用与校验
=================

``ProgramIR`` 保存有序量子调用、实验元数据和结果输出。调用通过
``kernel_ref`` 引用电路；程序 JSON 不嵌入电路，所以反序列化后仍需调用方提供
引用到电路的解析表。示例使用一位测量电路；``shot_count`` 仅描述请求，
``validate_program`` 不执行采样。

.. testcode:: program

   from qaiji import from_qasm3
   from qaiji.core.program import (
       ExperimentMetadata, ProgramIR, ProgramValidationError,
       QuantumInvocation, ResultOutput, compute_kernel_ref, validate_program,
   )

   circuit = from_qasm3("""OPENQASM 3.0;
   include "stdgates.inc";
   qubit[1] q;
   bit[1] c;
   h q[0];
   c[0] = measure q[0];
   """)
   kernel_ref = compute_kernel_ref(circuit)
   program = ProgramIR(
       quantum_invocations=(QuantumInvocation(kernel_ref),),
       experiment_metadata=ExperimentMetadata(shot_count=100),
       result_outputs=(ResultOutput(0, "c"),),
   )
   restored = ProgramIR.from_json(program.to_json())
   assert restored == program
   assert validate_program(restored, {kernel_ref: circuit}) is None

   changed = from_qasm3("""OPENQASM 3.0;
   include "stdgates.inc";
   qubit[1] q;
   bit[1] c;
   x q[0];
   c[0] = measure q[0];
   """)
   try:
       validate_program(restored, {kernel_ref: changed})
   except ProgramValidationError as error:
       assert len(error.problems) == 1
       assert "re-hashes to" in error.problems[0]
   else:
       raise AssertionError("修改后的电路不能沿用旧引用")

校验会重算每个被引用电路的哈希，并确认声明的输出寄存器每位都曾由测量写入。
结果只反映调用时刻提供的解析表；电路之后变动时必须重新校验。
``calibration_set_ref`` 与 ``device_profile_ref`` 只透传，不验证其内容或存在性。
程序模型不提供反馈运行时。接口细节见 :doc:`/api/program`；要把程序输出关联到
L2 测量事件，请继续阅读 :doc:`native-schedule`。
