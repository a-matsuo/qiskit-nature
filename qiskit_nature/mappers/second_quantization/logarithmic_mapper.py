# This code is part of Qiskit.
#
# (C) Copyright IBM 2021, 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""The Logarithmic Mapper."""

import operator

from enum import Enum
from fractions import Fraction
from functools import reduce
from typing import List, Union, Tuple

import numpy as np

from qiskit.opflow import PauliSumOp
from qiskit.quantum_info.operators import SparsePauliOp, Operator
from qiskit_nature.operators.second_quantization import SpinOp
from .spin_mapper import SpinMapper


class EmbedLocation(Enum):
    """Embed location type"""

    UPPER = "upper"
    LOWER = "lower"


class LogarithmicMapper(SpinMapper):
    """A mapper for Logarithmic spin-to-qubit mapping [1].
    In this local encoding transformation, each individual spin S system is represented via
    the lowest lying 2S+1 states in a qubit system with the minimal number of qubits needed to
    represent >= 2S+1 distinct states.

    [1]: Mathis, S. V., Guglielmo, M., & Ivano, T. (2020).
         Toward scalable simulations of lattice gauge theories on quantum computers.
         Phys. Rev. D, 102 (9), 094501. 10.1103/PhysRevD.102.094501
    """

    def __init__(self, padding: float = 1, location: EmbedLocation = EmbedLocation.UPPER) -> None:
        """
        Args:
            padding:
                When embedding a matrix into the upper/lower diagonal block of a 2^num_qubits by
                2^num_qubits matrix, pads the diagonal of the block matrix with
                the value of `padding`.

            location:
                Must be one of [`EmbedLocation.UPPER`, `EmbedLocation.LOWER`].
                This parameter sets whether
                the given matrix is embedded in the upper left hand corner or
                the lower right hand corner of the larger matrix.
                I.e. using location = `EmbedLocation.UPPER` returns the matrix:
                [[ matrix,    0             ],
                [   0   , padding * I]]

                Using location = `EmbedLocation.LOWER` returns the matrix:
                [[ padding * I,    0    ],
                [      0           ,  matrix ]]

        """
        super().__init__(allows_two_qubit_reduction=False)
        self._padding = padding
        self._location = location

    def map(self, second_q_op: SpinOp) -> PauliSumOp:
        """Map spins to qubits using the Logarithmic encoding.

        Args:
            second_q_op: Spins mapped to qubits.

        Returns:
            Qubit operators generated by the Logarithmic encoding
        """
        qubit_ops_list: List[PauliSumOp] = []

        # get logarithmic encoding of the general spin matrices.
        spinx, spiny, spinz, identity = self._logarithmic_encoding(second_q_op.spin)
        for idx, (_, coeff) in enumerate(second_q_op.to_list()):

            operatorlist: List[PauliSumOp] = []

            for n_x, n_y, n_z in zip(second_q_op.x[idx], second_q_op.y[idx], second_q_op.z[idx]):

                operator_on_spin_i: List[PauliSumOp] = []

                if n_x > 0:
                    operator_on_spin_i.append(reduce(operator.matmul, [spinx] * int(n_x)))

                if n_y > 0:
                    operator_on_spin_i.append(reduce(operator.matmul, [spiny] * int(n_y)))

                if n_z > 0:
                    operator_on_spin_i.append(reduce(operator.matmul, [spinz] * int(n_z)))

                if operator_on_spin_i:
                    single_operator_on_spin_i = reduce(operator.matmul, operator_on_spin_i)
                    operatorlist.append(single_operator_on_spin_i)

                else:
                    # If n_x=n_y=n_z=0, simply add the embedded Identity operator.
                    operatorlist.append(identity)

            # Now, we can tensor all operators in this list
            qubit_ops_list.append(coeff * reduce(operator.xor, reversed(operatorlist)))

        qubit_op = reduce(operator.add, qubit_ops_list)

        return qubit_op

    def _logarithmic_encoding(
        self, spin: Union[Fraction, int]
    ) -> Tuple[PauliSumOp, PauliSumOp, PauliSumOp, PauliSumOp]:
        """The logarithmic encoding.

        Args:
            spin: Positive half-integer (integer or half-odd-integer) that represents spin.

        Returns:
            A tuple containing four PauliSumOp.
        """
        spin_op_encoding: List[PauliSumOp] = []
        dspin = int(2 * spin + 1)
        num_qubits = int(np.ceil(np.log2(dspin)))

        # Get the spin matrices
        spin_matrices = [SpinOp(symbol, spin=spin).to_matrix() for symbol in "XYZ"]
        # Append the identity
        spin_matrices.append(np.eye(dspin))

        # Embed the spin matrices in a larger matrix of size 2**num_qubits x 2**num_qubits
        embedded_spin_matrices = [
            self._embed_matrix(matrix, num_qubits) for matrix in spin_matrices
        ]

        # Generate operators from these embedded spin matrices
        embedded_operators = [Operator(matrix) for matrix in embedded_spin_matrices]
        for op in embedded_operators:
            op = SparsePauliOp.from_operator(op)
            op.chop()
            spin_op_encoding.append(PauliSumOp(1.0 * op))

        return tuple(spin_op_encoding)  # type: ignore

    def _embed_matrix(
        self,
        matrix: np.ndarray,
        num_qubits: int,
    ) -> np.ndarray:
        """
        Embeds `matrix` into the upper/lower diagonal block of a 2^num_qubits by 2^num_qubits matrix
        and pads the diagonal of the upper left block matrix with the value of `padding`.
        Whether the upper/lower diagonal block is used depends on `location`.
        I.e. using location = 'EmbedLocation.UPPER' returns the matrix:
        [[ matrix,    0             ],
        [   0   , padding * I]]

        Using location = 'EmbedLocation.LOWER' returns the matrix:
        [[ padding * I,    0    ],
        [      0           ,  matrix ]]

        Args:
            matrix: The matrix (2D-array) to embed.
            num_qubits: The number of qubits on which the embedded matrix should act on.
            padding:
                The value of the diagonal elements of the upper left block of the embedded matrix.
            location: Must be one of [`EmbedLocation.UPPER`, `EmbedLocation.LOWER`]. This parameter sets
                whether the given matrix is embedded in the
                upper left hand corner or the lower right hand corner of the larger matrix.

        Returns:
            If `matrix` is of size 2^num_qubits, returns `matrix`.
            Else it returns the block matrix (I = identity)
            [[ padding * I,    0    ],
            [      0           , `matrix`]]

        Raises:
            ValueError: If location is neither "EmbedLocation.UPPER" nor "EmbedLocation.LOWER".
            ValueError: If the passed matrix does not fit into the space spanned by num_qubits.
        """
        full_dim = 1 << num_qubits
        subs_dim = matrix.shape[0]

        dim_diff = full_dim - subs_dim
        if dim_diff == 0:
            full_matrix = matrix

        elif dim_diff > 0:
            if self._location == EmbedLocation.LOWER:

                full_matrix = np.block(
                    [
                        [
                            np.eye(dim_diff) * self._padding,
                            np.zeros((dim_diff, subs_dim), dtype=complex),
                        ],
                        [np.zeros((subs_dim, dim_diff), dtype=complex), matrix],
                    ]
                )

            elif self._location == EmbedLocation.UPPER:

                full_matrix = np.block(
                    [
                        [matrix, np.zeros((subs_dim, dim_diff), dtype=complex)],
                        [
                            np.zeros((dim_diff, subs_dim), dtype=complex),
                            np.eye(dim_diff) * self._padding,
                        ],
                    ]
                )

            else:
                raise ValueError(
                    "location must be one of " "EmbedLocation.UPPER or EmbedLocation.LOWER"
                )

        else:
            raise ValueError(
                f"The given matrix does not fit into the space spanned by {num_qubits} qubits."
            )

        return full_matrix
