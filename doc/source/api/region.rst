L4 region 接口
==============

从 ``qaiji.core.semantics`` 显式导入。定义在 ``qaiji.core.semantics.region``。

region 是一个循环体或条件体。标识是结构路径：顶层条件体为 ``if:<位置>``，循环体为
``loop:<位置>``，循环内的条件体为 ``loop:<位置>/if:<循环体内位置>``。位置按节点计数，
声明不计入。标识由函数从结构计算，不存入节点。``regions_of`` 只遍历节点结构，不展开循环。

``annotate_looped`` 在展开电路上标注每个操作，并填写
:attr:`~qaiji.core.semantics.SemanticAnnotation.region_id`。``region_id`` 不进入语义摘要。
``check_preservation`` 的 ``region`` 参数取本页的标识，判决规则见
:doc:`/core-concepts/semantics`。其余 L4 接口见 :doc:`semantics`。

.. doctest::

   >>> from qaiji.codec import parse_looped_qasm3
   >>> from qaiji.core.semantics import annotate_looped, regions_of
   >>> looped = parse_looped_qasm3("qubit[2] q; for int i in [0:1] { x q[i]; }").circuit
   >>> [(r.id, r.kind, r.parent) for r in regions_of(looped)]
   [('loop:0', 'loop_body', None)]
   >>> [a.region_id for a in annotate_looped(looped)]
   ['loop:0', 'loop:0']

.. autoclass:: qaiji.core.semantics.Region
   :members:

.. autofunction:: qaiji.core.semantics.regions_of

.. autofunction:: qaiji.core.semantics.annotate_looped
