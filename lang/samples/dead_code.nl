// 样例 6：常量表达式 + 死代码消除
// dead 的计算结果从未被读取；DCE 应删除 dead 及其上游临时值。
// baseline 和优化档都必须输出 11，但优化档执行更少的指令。
// expect: 11

let x = 2 * 3 + 4;
let dead = x * 100;
let y = x + 1;
print y;
