// 样例 2：if / else + 比较运算
// 取 a、b 里较大的那个；再判断它的奇偶。
// expect: 17, 1

let a = 17;
let b = 9;
let max = 0;

if (a > b) {
  max = a;
} else {
  max = b;
}
print max;              // 17

// 奇偶：max - (max / 2) * 2  —— 整数除法，余数为 1 即为奇数
let odd = 0;
if (max - max / 2 * 2 == 1) {
  odd = 1;
}
print odd;              // 1（17 是奇数）
