"""
VM：三地址码解释器。

从"顺序遍历字节码"改成了 **pc 取指循环**——因为有了跳转，
执行顺序不再等于书写顺序。标签在开跑前先扫一遍建成 label -> pc 的表，
跳转就是一次 pc 赋值，O(1)。

关键点：执行时统计 instr_count（执行了多少条指令）。
这个数字是 benchmark 里衡量"优化有没有减少工作量"的核心指标之一 ——
优化前后跑同一程序，指令数的差值就是收益。循环程序里同一条指令
会被计很多次，这正是我们要的：它反映的是**动态**工作量，不是代码长度。

  ★ label 不计数。它是伪指令、运行时零开销（只是个地址标记）。
    如果把它算进 instr_count，那么"删掉一个空标签"这种不改变任何
    实际工作量的变换也会显示成"收益"，指标就被污染了。
"""


class VM:
    def __init__(self):
        self.vars = {}          # 变量名 -> 值（int，或数组时是 list）
        self.output = []
        self.instr_count = 0    # 实际执行的指令条数（label 不计）

    # 操作数解析：int 是字面量，str 是变量名（三地址码允许常量当操作数）
    def _val(self, operand):
        if isinstance(operand, int):
            return operand
        return self.vars[operand]

    def run(self, code, max_steps=10_000_000):
        self.vars = {}
        self.output = []
        self.instr_count = 0

        # 预扫描：标签 -> 指令下标
        labels = {}
        for pc, (op, dst, _s1, _s2) in enumerate(code):
            if op == "label":
                labels[dst] = pc

        pc = 0
        n = len(code)
        while pc < n:
            op, dst, s1, s2 = code[pc]

            if op == "label":       # 伪指令：不计数、不做事
                pc += 1
                continue

            self.instr_count += 1
            if self.instr_count > max_steps:
                raise RuntimeError("执行步数超上限，可能是死循环")

            if op == "copy":
                self.vars[dst] = self._val(s1)
            elif op == "add":
                self.vars[dst] = self._val(s1) + self._val(s2)
            elif op == "sub":
                self.vars[dst] = self._val(s1) - self._val(s2)
            elif op == "mul":
                self.vars[dst] = self._val(s1) * self._val(s2)
            elif op == "div":
                # 整数除法，保持语言"只有整数"的语义
                self.vars[dst] = self._val(s1) // self._val(s2)
            elif op == "lt":
                self.vars[dst] = int(self._val(s1) < self._val(s2))
            elif op == "gt":
                self.vars[dst] = int(self._val(s1) > self._val(s2))
            elif op == "le":
                self.vars[dst] = int(self._val(s1) <= self._val(s2))
            elif op == "ge":
                self.vars[dst] = int(self._val(s1) >= self._val(s2))
            elif op == "eq":
                self.vars[dst] = int(self._val(s1) == self._val(s2))
            elif op == "ne":
                self.vars[dst] = int(self._val(s1) != self._val(s2))
            elif op == "print":
                val = self._val(s1)
                self.output.append(val)
                print(val)
            elif op == "newarray":
                self.vars[dst] = [0] * self._val(s1)
            elif op == "load_idx":
                self.vars[dst] = self.vars[s1][self._val(s2)]
            elif op == "store_idx":
                self.vars[dst][self._val(s1)] = self._val(s2)
            elif op == "jump":
                pc = labels[dst]
                continue
            elif op == "jump_if_false":
                if self._val(s1) == 0:
                    pc = labels[dst]
                    continue
            else:
                raise ValueError(f"未知指令: {op}")

            pc += 1

        return self.output
