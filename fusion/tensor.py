from __future__ import annotations

from typing import Optional, Tuple, Type, Union

import numpy as np
from numpy import dtype

# from fusion.shape import shape_extractor

default_type = np.float32

ftype = Union[int, float, list, np.integer, np.floating, np.ndarray]


class Function:
    def __init__(self, *tensors: Tensor):
        self.parents = tensors

    def forward(self, *args):
        raise NotImplementedError("forward not implemented")

    def backward(self, *args):
        raise RuntimeError("backward not implemented")

    # @classmethod provides a way to define methods that operate on the class itself rather than instances of the class.
    # The apply method is used to instantiate and execute the forward pass of the function, returning a tensor representing the result.
    # context = Type[Function] that create this result: Add / Sum / Mul
    @classmethod
    def apply(cls: Type[Function], *parent: Tensor):
        context = cls(*parent)
        output = Tensor(context.forward(*parent))
        output._context = context
        return output


class Sum(Function):
    def forward(self, input: Tensor):
        return np.sum(input.ndata)

    def backward(self, output: Tensor):
        # this line unpack the tuple of (*self.parents)
        x, = self.parents
        return np.ones(x.shape) * output.ndata
        # return np.ones_like(x.ndata) * output.ndata


class Relu(Function):
    def forward(self, input:Tensor):
        return np.maximum(input.ndata, 0)

    def backward(self, output: Tensor):
        x, = self.parents
        output_gradient = np.copy(output.ndata)
        output_gradient[x.ndata <= 0] = 0
        return output_gradient


class Add(Function):
    def forward(self, x: Tensor, y: Tensor):
        return np.add(x.ndata, y.ndata)

    def backward(self, output: Tensor):
        return output.ndata, output.ndata


class Mul(Function):
    def forward(self, x: Tensor, y: Tensor):
        return np.multiply(x.ndata, y.ndata)

    def backward(self, output: Tensor):
        x, y = self.parents
        return output.ndata * y.ndata, output.ndata * x.ndata


class Dot(Function):
    def forward(self, x: Tensor, y: Tensor):
        # x(A, B)
        # y(B, C)
        # output(A, C)
        return np.dot(x.ndata, y.ndata)

    def backward(self, output: Tensor):
        x, y = self.parents
        # output :  (A, C)
        # y.T :     (C, B)
        # result :  (A, B)
        # output.T :(C, A)
        # x :       (A, B)
        # result :  (C, B).T // we then transpose it to go in y_gradient
        return np.dot(output.ndata, y.ndata.T), np.dot(output.ndata.T, x.ndata).T


class Log(Function):
    def forward(self, x:Tensor):
        return np.log(x.ndata)

    def backward(self, output: Tensor):
        x, = self.parents
        return output.ndata * (1 / x.ndata)

# Movement ops, modify size of Tensor
# class Expand(Function):
#     def forward(self, x: Tensor, output_shape: Tuple):
#         self.input_shape = x.shape
#         self.output_shape = output_shape
#         self.diff = shape_extractor(self.input_shape, self.output_shape)
#         return np.tile(x.ndata, (self.diff,1))
#
#     def backward(self, output: Tensor):
#         return output.ndata


class Tensor:
    # https://wiki.python.org/moin/UsingSlots
    # slots are more efficient in terms of memory space and speed of access, and a bit safer than the default Python method of data access
    # __slots__ = "ndata", "need_gradient", "gradient", "_context"

    # how to handle various type for ndata ?
    def __init__(self, data: ftype, requires_gradient: Optional[bool] = None):
        # True for parameters training / False for inference / inputs / labels
        self.requires_gradient: Optional[bool] = requires_gradient

        # for the zero_grad we set to None the value of gradients and we can use the None to do operation like
        # we create a copy in shape of the tensor and zeroed all the value
        self.gradient: Optional[Tensor] = None

        # Context: internal variables used for autograd graph construction
        # _ mean private context
        self._context: Optional[Function] = None

        if not isinstance(data, ftype):
            raise RuntimeError(f"data of type :{type(data)} is not accepted")

        if isinstance(data, (int, float, list, np.integer, np.floating)):
            if isinstance(data, int):
                self.ndata = np.array(data, dtype=np.integer)
            if isinstance(data, float):
                self.ndata = np.array(data, dtype=default_type)
            else:
                self.ndata = np.array(data)
            return

        if isinstance(data, np.ndarray):
            self.ndata = data
            return

    # @property is just a getter() | in our case it gets the shape()
    @property
    def shape(self) -> Tuple[int, ...]:
        return self.ndata.shape

    @property
    def dtype(self) -> dtype:
        return self.ndata.dtype

    # def dtype(self) -> dtype: return np.dtype(self.ndata)

    # def numpy(self) -> np.ndarray: return self.ndata
    # def numpy(self) -> np.ndarray: return self.lazydata.numpy()

    def topological_sort(self):
        def _topological_sort(node, node_visited, graph_sorted):
            if node not in node_visited:
                if getattr(node, "_context", None):
                    node_visited.add(node)
                    for parent in node._context.parents:
                        _topological_sort(parent, node_visited, graph_sorted)
                        # yield / is for lazy, thus yielding the data
                    graph_sorted.append(node)
            return graph_sorted

        return _topological_sort(self, set(), [])

    def backward(self):
        # First gradient is always one
        self.gradient = Tensor(np.ones(self.shape), requires_gradient=False)
        # if self.shape == ():
        #     self.gradient = Tensor(1, requires_gradient=False)
        # else:
        #     print(f"backward can only be perform on scalar value and shape is: {self.shape}")
        #     return

        # self.gradient = Tensor(np.ones_like(self.ndata), requires_gradient=False)

        for node in reversed(self.topological_sort()):
            gradients = node._context.backward(node.gradient)
            # we compute gradient // one for each parents
            if len(node._context.parents) == 1:
                gradients = [Tensor(gradients, requires_gradient=False)]
            else:
                gradients = [Tensor(g, requires_gradient=False) for g in gradients]
            for parent, gradient in zip(node._context.parents, gradients):
                    # if a Tensor is used multiple time in our graph, we add gradient
                    parent.gradient = gradient if parent.gradient is None else (parent.gradient + gradient)
                    # parent.gradient = gradient
            del node._context
        return self

    def sum(self):
        return Sum.apply(self)

    def add(self, other):
        return Add.apply(self, other)

    def __add__(self, other):
        return self.add(other)

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
        one_div = Tensor(1/other.ndata)
        return self.mul(one_div)

    def __truediv__(self, other):
        return self.div(other)

    def log(self):
        return Log.apply(self)

    # def pow(self):
    #     return Pow.apply(self, other)

    def mean(self):
        one_div = Tensor(np.array([1/self.ndata.size]))
        return self.sum().mul(one_div)

    # def expand(self, shape):
    #     return Expand.apply(self, shape)

    def transpose(self):
        self.ndata = self.ndata.T
        return self

    def __getattr__(self, name):
        if name == 'T':
            return self.transpose()
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def __repr__(self) -> str:
        # assert self.ndata.shape is not None
        # return f'<Tensor(shape={self.ndata.shape})>'
        # we do not store operation on the Tensor: its in Function
        if self.gradient is not None:
            return f"<Tensor(ndata={self.ndata}, gradient={self.gradient.ndata} ,requires_gradient={self.requires_gradient})>"
        else:
            return f"<Tensor(ndata={self.ndata}, requires_gradient={self.requires_gradient})>"
