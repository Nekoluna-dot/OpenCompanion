let handler = null;
export function setUnauthorizedHandler(fn) {
  handler = fn;
}
export function onUnauthorized() {
  if (handler) handler();
}
