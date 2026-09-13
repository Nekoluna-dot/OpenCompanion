<script setup>
import { ref, onMounted, onUnmounted, watch } from "vue";
import { app } from "../lib/state.js";
import { subscribeLogs } from "../lib/logs.js";

const props = defineProps({
  limit: { type: Number, default: 500 },
  filter: { type: String, default: "" },
});

const el = ref(null);
let unsub = null;

function matches(line) {
  if (!props.filter) return true;
  return line.toLowerCase().includes(props.filter.toLowerCase());
}

function scrollBottom() {
  if (el.value) el.value.scrollTop = el.value.scrollHeight;
}

function onLine(line) {
  if (!el.value) return;
  if (!matches(line)) return;
  const div = document.createElement("div");
  div.className = "line";
  div.textContent = line;
  el.value.appendChild(div);
  while (el.value.childElementCount > props.limit) el.value.removeChild(el.value.firstElementChild);
  scrollBottom();
}

function rebuild() {
  if (!el.value) return;
  el.value.innerHTML = "";
  app.logs.slice(-props.limit).forEach(line => {
    if (!matches(line)) return;
    const div = document.createElement("div");
    div.className = "line";
    div.textContent = line;
    el.value.appendChild(div);
  });
  scrollBottom();
}

onMounted(() => {
  rebuild();
  unsub = subscribeLogs(onLine);
});
onUnmounted(() => { if (unsub) unsub(); });

watch(() => props.filter, rebuild);

defineExpose({ rebuild, scrollBottom, el });
</script>

<template>
  <div id="logview" ref="el"></div>
</template>
