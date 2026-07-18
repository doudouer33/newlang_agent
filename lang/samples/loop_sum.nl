// 样例 3：while 循环
// 累加 1..n，n = 10 → 1+2+...+10 = 55
// expect: 55

let n = 10;
let i = 1;
let sum = 0;

while (i <= n) {
  sum = sum + i;
  i = i + 1;
}

print sum;              // 55
