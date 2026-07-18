// 样例 4：数组 + 嵌套循环（向量点积）
// a[i] = i+1  →  [1,2,3,4,5]
// b[i] = 2*(i+1) →  [2,4,6,8,10]
// dot = sum(a[i]*b[i]) = 2+8+18+32+50 = 110
// 同时打印 a 的元素和 = 1+2+3+4+5 = 15
// expect: 15, 110
//
// 这个样例是给优化 pass 准备的"试金石"：循环体里 a[i]*b[i] 每轮都要
// 重算下标、重读数组，正是 LICM / 强度削弱 / 公共子表达式能发力的形状。

let n = 5;
let a = array(n);
let b = array(n);

// 初始化
let i = 0;
while (i < n) {
  a[i] = i + 1;
  b[i] = (i + 1) * 2;
  i = i + 1;
}

// 数组求和
let s = 0;
i = 0;
while (i < n) {
  s = s + a[i];
  i = i + 1;
}
print s;                // 15

// 点积
let dot = 0;
i = 0;
while (i < n) {
  dot = dot + a[i] * b[i];
  i = i + 1;
}
print dot;              // 110
