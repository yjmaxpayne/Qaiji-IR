L5 程序：引用与校验
===================

本页演示 L5 程序记录的用法：计算内核引用、构造程序、JSON 往返，以及校验程序。
``ProgramIR`` 保存有序的量子调用、实验元数据和结果输出。每个调用通过 ``kernel_ref``
引用电路。程序 JSON 不含电路，所以读回程序后，调用方仍须提供从引用到电路的解析表。
前置页：:doc:`semantics`。

示例使用一个单比特测量电路。``shot_count`` 只描述请求；``validate_program`` 不执行采样。

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

校验重新计算每个被引用电路的哈希，并确认每个声明的输出寄存器的每一位都曾由测量写入。
结论只对调用时刻的解析表成立；此后电路改变时，必须重新校验。
``calibration_set_ref`` 与 ``device_profile_ref`` 只透传，本包不验证它们的内容或是否存在。
程序模型不提供反馈运行时。

相关页面：校验的完整规则与限制见 :doc:`/core-concepts/program`；完整接口见 :doc:`/api/program`。

把程序输出关联到 L2 测量事件，见 :doc:`native-schedule` 的「关联 L5 输出」一节。

下一步：:doc:`physical` 说明不在 L5 到 L0 降级链上的 P 层。
