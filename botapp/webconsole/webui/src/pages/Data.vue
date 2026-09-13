<script setup>
import { ref, onMounted } from "vue";
import { Button } from "animal-island-ui-vue";
import { api, toast, fmtSize } from "../lib/api.js";

const paths = ref([]);

async function loadData() {
  try {
    const d = await api("/api/data/paths");
    paths.value = d.paths || [];
  } catch (e) { toast(e.message, "err"); }
}

async function delPath(p) {
  if (!confirm("确定删除？\n\n" + p.path)) return;
  try {
    const r = await api("/api/data/delete", "POST", { target: p.path });
    toast(r.result, "ok");
    loadData();
  } catch (e) { toast(e.message, "err"); }
}

async function factoryReset() {
  if (!confirm("恢复出厂设置\n\n将清空全部用户数据并重置 API 密钥，此操作不可恢复！")) return;
  if (!confirm("最后确认：真的要恢复出厂设置吗？")) return;
  try {
    const r = await api("/api/data/factory_reset", "POST", {});
    toast(r.result, "ok");
    loadData();
    location.hash = "#/config";
  } catch (e) { toast(e.message, "err"); }
}

async function factoryResetFull() {
  const msg = "彻底恢复出厂设置\n\n" +
    "1) 清空全部用户数据(weilink/对话/OB记忆/日志)\n" +
    "2) 清空 data/ 目录(登录密码、webconsole 设置、事件库等)\n" +
    "3) config.ini 重置为初始默认配置(需重新填 API 密钥、重新设登录密码)\n\n" +
    "此操作不可恢复！";
  if (!confirm(msg)) return;
  const code = prompt("请键入 RESET 以最终确认：");
  if (code !== "RESET") { toast("已取消", "err"); return; }
  if (!confirm("最后确认：真的要彻底恢复出厂吗？")) return;
  try {
    const r = await api("/api/data/factory_reset_full", "POST", {});
    toast(r.result, "ok");
    loadData();
    location.hash = "#/config";
  } catch (e) { toast(e.message, "err"); }
}

onMounted(loadData);
</script>

<template>
  <div class="card">
    <div class="card-title">数据路径</div>
    <table class="tbl">
      <thead><tr><th>说明</th><th>路径</th><th>大小</th><th></th></tr></thead>
      <tbody>
        <tr v-for="(p, i) in paths" :key="i">
          <td>{{ p.label }}</td>
          <td class="mono" style="font-size:12px">{{ p.path }}</td>
          <td>{{ fmtSize(p.size) }}</td>
          <td class="actions"><Button type="primary" danger size="small" @click="delPath(p)">删除</Button></td>
        </tr>
        <tr v-if="!paths.length"><td colspan="4" class="empty">暂无数据</td></tr>
      </tbody>
    </table>
    <div class="muted" style="margin-top:8px">删除后不可恢复；平台数据删除后需重新扫码登录。</div>
  </div>
  <div class="card">
    <div class="card-title" style="color:var(--pg-red)">危险操作</div>
    <div class="row">
      <Button type="primary" danger @click="factoryReset">恢复出厂设置</Button>
      <span class="muted">清空全部用户数据（weilink / 对话 / OB 记忆 / 日志 / 运行锁），并把 API 密钥替换为占位符</span>
    </div>
    <div class="row" style="margin-top:10px">
      <Button type="dashed" danger @click="factoryResetFull">彻底恢复出厂</Button>
      <span class="muted">在恢复出厂基础上，再清空 data/ 目录（登录密码 / webconsole 设置 / 事件库等）并把 config.ini 重置为初始默认配置</span>
    </div>
  </div>
</template>
