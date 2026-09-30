# Copyright 2026 Qaiji-IR core developer: Ye Jun <yjmaxpayne@hotmail.com>
# SPDX-License-Identifier: Apache-2.0
"""光学适配器 domain 层的冻结事实：逐字源码片段及其出处，不含任何逻辑。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Fact:
    """源文件某一行段的逐字文本及其出处。

    ``verbatim`` 是唯一事实源：它等于源文件第 ``lines[0]..lines[1]`` 行按换行拼接的原文。
    ``physical_claim`` 只进入失败消息，判据不读它。
    """

    fact_id: str
    source_path: str
    lines: tuple[int, int]
    commit: str
    extracted_on: date
    verbatim: str
    physical_claim: str


_COMMIT = "d702b677"
_EXTRACTED_ON = date(2026, 9, 23)
_SINGLE_QUBIT = "src/quantempo/domain/quantum/gates/single_qubit.py"
_GATE_BASE = "src/quantempo/domain/quantum/gates/base.py"

FACTS: tuple[Fact, ...] = (
    Fact(
        fact_id="XR-SP",
        source_path=_SINGLE_QUBIT,
        lines=(197, 222),
        commit=_COMMIT,
        extracted_on=_EXTRACTED_ON,
        verbatim=r'''class Sp(Gate):
    """Returns the Sigma-plus matrix for the given qubit.

    Args:
        q0 (int): The qubit id number.

    Mathematical Context:

    .. math::

        \\sigma^+ = \\begin{pmatrix} 0 & 1 \\\\ 0 & 0 \\end{pmatrix}

    Notes:
        Raising operator that maps :math:`|1\\rangle \\to |0\\rangle`
        (ground to excited state).
        QuanTempo convention: :math:`|0\\rangle` = excited state,
        :math:`|1\\rangle` = ground state.
    """

    def __init__(self, q0):
        self.target_qubits = (q0,)
        matrix = torch.tensor([[0.0, 1.0], [0.0, 0.0]], dtype=Gate.dtype)
        self._assemble(matrix)

    def __str__(self):
        return f"Sigma-plus Gate on qubit {self.target_qubits[0]}"''',
        physical_claim="Sp is the raising operator: ground -> excited",
    ),
    Fact(
        fact_id="XR-SM",
        source_path=_SINGLE_QUBIT,
        lines=(225, 250),
        commit=_COMMIT,
        extracted_on=_EXTRACTED_ON,
        verbatim=r'''class Sm(Gate):
    """Returns the Sigma-minus matrix for the given qubit.

    Args:
        q0 (int): The qubit id number.

    Mathematical Context:

    .. math::

        \\sigma^- = \\begin{pmatrix} 0 & 0 \\\\ 1 & 0 \\end{pmatrix}

    Notes:
        Lowering operator that maps :math:`|0\\rangle \\to |1\\rangle`
        (excited to ground state).
        QuanTempo convention: :math:`|0\\rangle` = excited state,
        :math:`|1\\rangle` = ground state.
    """

    def __init__(self, q0):
        self.target_qubits = (q0,)
        matrix = torch.tensor([[0.0, 0.0], [1.0, 0.0]], dtype=Gate.dtype)
        self._assemble(matrix)

    def __str__(self):
        return f"Sigma-minus Gate on qubit {self.target_qubits[0]}"''',
        physical_claim="Sm is the lowering operator: excited -> ground",
    ),
    Fact(
        fact_id="XR-Z",
        source_path=_SINGLE_QUBIT,
        lines=(116, 135),
        commit=_COMMIT,
        extracted_on=_EXTRACTED_ON,
        verbatim=r'''class PauliZ(Gate):
    """Apply the Pauli-Z gate to the specified qubit.

    Args:
        q0 (int): The qubit id number.

    Mathematical Context:

    .. math::

        Z = \\begin{pmatrix} 1 & 0 \\\\ 0 & -1 \\end{pmatrix}
    """

    def __init__(self, q0):
        self.target_qubits = (q0,)
        matrix = torch.tensor([[1.0, 0.0], [0.0, -1.0]], dtype=Gate.dtype)
        self._assemble(matrix)

    def __str__(self):
        return f"Pauli-Z Gate on qubit {self.target_qubits[0]}"''',
        physical_claim="PauliZ is diag(1, -1) in storage order",
    ),
    Fact(
        fact_id="XR-RZ",
        source_path=_SINGLE_QUBIT,
        lines=(351, 378),
        commit=_COMMIT,
        extracted_on=_EXTRACTED_ON,
        verbatim=r'''class RZ(Gate):
    """Apply the RZ gate to the given qubit.

    Args:
        q0 (int): The qubit id number.
        theta (float): The rotation angle.

    Mathematical Context:

    .. math::

        e^{-i \\frac{\\theta}{2} Z} =
        \\begin{pmatrix}
        e^{-i\\theta/2} & 0 \\\\
        0 & e^{i\\theta/2}
        \\end{pmatrix}
    """

    def __init__(self, q0, theta):
        self.target_qubits = (q0,)
        theta = self._semantic_parameter("theta", theta)
        z = torch.zeros((), dtype=Gate.dtype, device=Gate.device)
        row0 = torch.stack([torch.exp(-1j * theta / 2.0).to(Gate.device), z])
        row1 = torch.stack([z, torch.exp(1j * theta / 2.0).to(Gate.device)])
        self._assemble(torch.stack([row0, row1]))

    def __str__(self):
        return f"RZ Gate on qubit {self.target_qubits[0]}"''',
        physical_claim="RZ(theta) = exp(-i*theta*Z/2)",
    ),
    Fact(
        fact_id="XR-ASSEMBLE",
        source_path=_GATE_BASE,
        lines=(344, 354),
        commit=_COMMIT,
        extracted_on=_EXTRACTED_ON,
        verbatim=r'''    def _assemble(self, matrix, mpo_shape=None):
        """Place matrix on active dtype/device, derive MPO, init base.

        ``mpo_shape=None`` keeps the placed matrix as its own MPO (single-site
        gates); a shape reshapes the placed matrix into the MPO (multi-site
        gates). Calls ``Gate.__init__`` (not ``super().__init__``) so the base
        initializer is reached regardless of the concrete gate's MRO.
        """
        matrix = matrix.to(dtype=Gate.dtype, device=Gate.device)
        mpo = matrix if mpo_shape is None else torch.reshape(matrix, mpo_shape)
        Gate.__init__(self, matrix, mpo)''',
        physical_claim="single-site gates store the matrix unchanged",
    ),
    Fact(
        fact_id="XR-SEMPARAM",
        source_path=_GATE_BASE,
        lines=(329, 342),
        commit=_COMMIT,
        extracted_on=_EXTRACTED_ON,
        verbatim=r'''    def _semantic_parameter(self, name, value):
        """Normalize ``value`` and record it as this gate's ``name`` parameter.

        The single point where a parametrized gate turns a caller-supplied
        angle into the tensor that enters its matrix, so recording it here
        makes the metadata true by construction rather than by convention.
        """
        tensor = self._as_tensor(value)
        try:
            recorded = self._semantic_parameters
        except AttributeError:
            recorded = self._semantic_parameters = {}
        recorded[name] = tensor
        return tensor''',
        physical_claim="_semantic_parameter returns the angle tensor unchanged",
    ),
    Fact(
        fact_id="XR-APPLY-MPS",
        source_path="src/quantempo/core/constants.py",
        lines=(105, 105),
        commit=_COMMIT,
        extracted_on=_EXTRACTED_ON,
        verbatim=r'''            self.str1[0] = "jx,ixk->ijk"''',
        physical_claim="MPS single-site contraction applies a gate as M[out, in]",
    ),
    Fact(
        fact_id="XR-APPLY-SV",
        source_path="src/quantempo/domain/quantum/gate_application/strategies/statevector_strategy.py",
        lines=(300, 301),
        commit=_COMMIT,
        extracted_on=_EXTRACTED_ON,
        verbatim=r"""            psi_perm = psi.permute(order).contiguous().view(phys_dim**k, -1)
            psi_new_front = torch.matmul(matrix, psi_perm)""",
        physical_claim="state-vector path left-multiplies the gate matrix",
    ),
    Fact(
        fact_id="XR-INIT",
        source_path="src/quantempo/domain/backends/native_backend.py",
        lines=(281, 282),
        commit=_COMMIT,
        extracted_on=_EXTRACTED_ON,
        verbatim=r"""        # Initialize with all ground state (all 1's = all spin down in quantum optics convention)
        spin_string = "1" * num_sites""",
        physical_claim="an all-'1' spin string is the all-ground initial state",
    ),
    Fact(
        fact_id="XR-INIT-PARSE",
        source_path="src/quantempo/domain/quantum/circuits.py",
        lines=(271, 272),
        commit=_COMMIT,
        extracted_on=_EXTRACTED_ON,
        verbatim=r"""        if isinstance(spin_string, str):
            resolved_spin_string = tuple(int(c) for c in spin_string)""",
        physical_claim="spin character c selects basis index int(c)",
    ),
)
