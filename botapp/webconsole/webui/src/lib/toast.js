import { reactive } from "vue";

export const toastState = reactive({ items: [] });
let seq = 0;

export function toast(msg, type = "") {
  const id = ++seq;
  toastState.items.push({ id, msg, type });
  setTimeout(() => {
    const i = toastState.items.findIndex(t => t.id === id);
    if (i >= 0) toastState.items.splice(i, 1);
  }, 4200);
}
