<script setup>
import { ref } from "vue";
import { Button, Input, Checkbox } from "animal-island-ui-vue";
import { api, toast } from "../lib/api.js";
import LogView from "../components/LogView.vue";

const filterText = ref("");
const autoScroll = ref(true);

function clearLogs() {
  api("/api/logs/clear", "POST", {}).then(() => {
    toast("已清空日志缓冲", "ok");
  }).catch(e => toast(e.message, "err"));
}
</script>

<template>
  <div class="card">
    <div class="card-title">运行日志</div>
    <div class="log-tools">
      <Button @click="clearLogs">清空日志</Button>
      <Checkbox v-model:checked="autoScroll">自动滚动</Checkbox>
      <Input v-model="filterText" placeholder="过滤关键词…" allow-clear style="width:220px" />
    </div>
    <LogView :limit="2000" :filter="filterText" />
  </div>
</template>
