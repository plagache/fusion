from __future__ import annotations

import os
from typing import Optional, Tuple, Type

import numpy as np
from numpy import dtype

from fusion.graph import draw_graph


class Function:
    def __init__(self, *tensors: Tensor):
        self.parents = tensors

    def forward(self, *args):
        raise NotImplementedError("forward not implemented")

    def backward(self, *args):
        raise RuntimeError("backward not implemented")

    @classmethod
    def apply(cls: Type[Function], *parent: Tensor):
        context = cls(*parent)
        output = Tensor(context.forward(*parent))
        output._context = context
        return output


class Sum(Function):
    def forward(self, x: Tensor):
        return np.sum(x.data)

    def backward(self, output: Tensor):
        (x,) = self.parents
        return np.ones(x.shape) * output.data
        # return np.ones_like(x.data) * output.data


class Relu(Function):
    def forward(self, x: Tensor):
        return np.maximum(x.data, 0)

    def backward(self, output: Tensor):
        (x,) = self.parents
        output_gradient = np.copy(output.data)
        output_gradient[x.data <= 0] = 0
        return output_gradient


class Add(Function):
    def forward(self, x: Tensor, y: Tensor):
        return np.add(x.data, y.data)

    def backward(self, output: Tensor):
        return output.data, output.data


class Mul(Function):
    def forward(self, x: Tensor, y: Tensor):
        return np.multiply(x.data, y.data)

    def backward(self, output: Tensor):
        x, y = self.parents
        return y.data * output.data, x.data * output.data


class Dot(Function):
    def forward(self, x: Tensor, y: Tensor):
        # x(A, B)
        # y(B, C)
        # output(A, C)
        return np.dot(x.data, y.data)

    def backward(self, output: Tensor):
        x, y = self.parents
        # output :  (A, C)
        # y.T :     (C, B)
        # result :  (A, B)
        # output.T :(C, A)
        # x :       (A, B)
        # result :  (C, B).T // we then transpose it to go in y_gradient
        return np.dot(output.data, y.data.T), np.dot(output.data.T, x.data).T


class Log(Function):
    def forward(self, x: Tensor):
        return np.log(x.data)

    def backward(self, output: Tensor):
        (x,) = self.parents
        return (1 / x.data) * output.data


class Pow(Function):
    def forward(self, x: Tensor, power: Tensor):
        return np.power(x.data, power)

    def backward(self, output: Tensor):
        x, power = self.parents
        return (power * np.power(x.data, (power - 1))) * output.data


class Exp(Function):
    def forward(self, x: Tensor):
        return np.exp(x.data)

    def backward(self, output: Tensor):
        (x,) = self.parents
        return np.exp(x.data) * output.data


class Sigmoid(Function):
    def forward(self, x: Tensor):
        σ = 1 / (1 + np.exp(-x.data))
        return σ
        return 1 / (1 + np.exp(-x.data))
        return np.exp(x.data) / (1 + np.exp(x.data))

    def backward(self, output: Tensor):
        (x,) = self.parents
        # σ = np.exp(x.data) / (1 + np.exp(x.data))
        σ = 1 / (1 + np.exp(-x.data))
        return σ * (1 - σ) * output.data


# Movement ops, modify size of Tensor
# class Expand(Function):
#     def forward(self, x: Tensor, output_shape: Tuple):
#         self.input_shape = x.shape
#         self.output_shape = output_shape
#         self.diff = shape_extractor(self.input_shape, self.output_shape)
#         return np.tile(x.data, (self.diff,1))
#
#     def backward(self, output: Tensor):
#         return output.data


class Tensor:
    # how to handle various type for data ?
    # i let numpy raise error
    def __init__(self, data):
        # for the zero_grad we set to None the value of gradients and we can use the None to do operation like
        # we create a copy in shape of the tensor and zeroed all the value
        self.gradient: Optional[Tensor] = None

        # Context: internal variables used for autograd graph construction
        # _ mean private context
        self._context: Optional[Function] = None

        if isinstance(data, np.ndarray):
            self.data = data
        else:
            self.data = np.array(data)

        if not np.issubdtype(self.data.dtype, np.number):
            raise TypeError(f"Invalid data type {self.data.dtype}. Numeric data required.")

    # @property is just a getter() | in our case it gets the shape()
    @property
    def shape(self) -> Tuple[int, ...]:
        return self.data.shape

    @property
    def dtype(self) -> dtype:
        return self.data.dtype

    @property
    def tensor_attribute(self) -> str:
        return f"<{self.shape!r}, {self.dtype!r}>"

    def topological_sort(self):
        def _topological_sort(node, node_visited, graph_sorted):
            if node not in node_visited:
                if getattr(node, "_context", None):
                    node_visited.add(node)
                    for parent in node._context.parents:
                        _topological_sort(parent, node_visited, graph_sorted)
                    graph_sorted.append(node)
            return graph_sorted

        return _topological_sort(self, set(), [])

    def backward(self):
        # First gradient is always one
        self.gradient = Tensor(np.ones(self.shape))
        # if self.shape == ():
        #     self.gradient = Tensor(1, requires_gradient=False)
        # else:
        #     print(f"backward can only be perform on scalar value and shape is: {self.shape}")
        #     return

        # self.gradient = Tensor(np.ones_like(self.data))

        # print(self.topological_sort())
        if os.getenv("GRAPH") == "1":
            draw_graph(self, "graph")

        for node in reversed(self.topological_sort()):
            gradients = node._context.backward(node.gradient)
            # we compute gradient // one for each parents
            if len(node._context.parents) == 1:
                gradients = [Tensor(gradients)]
            else:
                gradients = [Tensor(g) for g in gradients]
            for parent, gradient in zip(node._context.parents, gradients):
                # if a Tensor is used multiple time in our graph, we add gradient
                # print(parent)
                # print(type(parent))
                # print(parent.data)
                parent.gradient = gradient if parent.gradient is None else (parent.gradient + gradient)
            del node._context
        return self

    def sum(self):
        return Sum.apply(self)

    def add(self, other):
        return Add.apply(self, other)

    def __add__(self, other):
        return self.add(other)

    def __neg__(self):
        return self.mul(Tensor(-1))

    def sub(self, other):
        return self.add(-other)

    def __sub__(self, other):
        return self.sub(other)

    def mul(self, other):
        return Mul.apply(self, other)

    def __mul__(self, other):
        return self.mul(other)

    def relu(self):
        return Relu.apply(self)

    def dot(self, other):
        return Dot.apply(self, other)

    def div(self, other):
        one_div = Tensor(1 / other.data)
        return self.mul(one_div)

    def __truediv__(self, other):
        return self.div(other)

    def log(self):
        return Log.apply(self)

    def pow(self, power):
        print(isinstance(power, Tensor))
        if not isinstance(power, Tensor):
            power = Tensor(power)
        return Pow.apply(self, power)

    def __pow__(self, power):
        print(isinstance(power, Tensor))
        if not isinstance(power, Tensor):
            power = Tensor(power)
        return self.pow(power)

    def mean(self):
        one_div = Tensor(np.array([1 / self.data.size]))
        return self.sum().mul(one_div)

    def exp(self):
        return Exp.apply(self)

    def sigmoid(self):
        return Sigmoid.apply(self)

    # def logistic(self):
    #     return Tensor(1) / (Tensor(1) + -(self).exp())

    # def expand(self, shape):
    #     return Expand.apply(self, shape)

    def transpose(self):
        self.data = self.data.T
        return self

    def __getattr__(self, name):
        if name == "T":
            return self.transpose()
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def __repr__(self) -> str:
        return f"<Tensor {self.tensor_attribute!r} with gradient {(self.tensor_attribute if self.gradient is not None else None)!r}>"
