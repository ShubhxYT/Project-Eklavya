export const average = (arr: number[]) =>
  arr.reduce((a, b) => a + b, 0) / (arr.length || 1);

export default average;
