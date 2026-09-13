<script setup>
import { ref, onMounted } from "vue";
import { Button, Input, Textarea, Tag, Empty } from "animal-island-ui-vue";
import { api, toast } from "../lib/api.js";

const presets = ref([]);
const active = ref("");
const editing = ref("");
const edDesc = ref("");
const edPrompt = ref("");
const edExtra = ref("");
const newName = ref("");

async function refreshList() {
  try {
    const d = await api("/api/prompts");
    presets.value = d.presets || [];
    active.value = d.active || "";
    editing.value = d.active || "";
    await loadPreset(editing.value);
  } catch (e) { toast(e.message, "err"); }
}

async function loadPreset(name) {
  if (!name) { editing.value = ""; edDesc.value = ""; edPrompt.value = ""; edExtra.value = ""; return; }
  try {
    const p = await api(`/api/prompts/${encodeURIComponent(name)}`);
    editing.value = name;
    edDesc.value = p.description || "";
    edPrompt.value = p.prompt || "";
    edExtra.value = p.extra || "";
  } catch (e) {
    // 预设可能刚被删除/改名（读取时已不存在）：静默清空，不弹错误
    if (editing.value === name) { editing.value = ""; edDesc.value = ""; edPrompt.value = ""; edExtra.value = ""; }
  }
}

async function savePreset() {
  if (!editing.value) { toast("未选择", "err"); return; }
  try {
    await api(`/api/prompts/${encodeURIComponent(editing.value)}`, "POST", {
      prompt: edPrompt.value, extra: edExtra.value, description: edDesc.value,
    });
    toast("已保存", "ok");
    await refreshList();
  } catch (e) { toast(e.message, "err"); }
}

async function activatePreset(name) {
  try {
    await api(`/api/prompts/${encodeURIComponent(name)}/activate`, "POST", {});
    toast(`已切换到 ${name}`, "ok");
    await refreshList();
  } catch (e) { toast(e.message, "err"); }
}

async function deletePreset(name) {
  if (!confirm(`删除 ${name}?`)) return;
  try {
    await api(`/api/prompts/${encodeURIComponent(name)}/delete`, "POST", {});
    toast("已删除", "ok");
    await refreshList();
  } catch (e) { toast(e.message, "err"); }
}

async function newPreset() {
  const name = newName.value.trim();
  if (!name) { toast("输入名称", "err"); return; }
  try {
    const r = await api("/api/prompts", "POST", { name, description: "", prompt: "", extra: "" });
    newName.value = "";
    await refreshList();
    loadPreset(r.name);
  } catch (e) { toast(e.message, "err"); }
}

onMounted(refreshList);
</script>

<template>
  <div class="presets-layout">
    <div class="card">
      <div class="card-title">预设</div>
      <div class="new-row">
        <Input v-model="newName" placeholder="名称" maxlength="64" allow-clear />
        <Button type="primary" @click="newPreset">新建</Button>
      </div>
      <div>
        <Empty v-if="!presets.length" title="暂无预设" description="新建一个以开始编辑人设" />
        <div v-for="p in presets" :key="p.name" class="preset-row" :class="{ active: p.active }">
          <div class="preset-info">
            <span class="preset-name">{{ p.name }}</span>
            <span v-if="p.description" class="preset-desc">{{ p.description }}</span>
            <Tag v-if="p.active" color="mint">当前</Tag>
          </div>
          <div class="preset-actions">
            <Button size="small" @click="loadPreset(p.name)">编辑</Button>
            <Button size="small" type="primary" :disabled="p.active" @click="activatePreset(p.name)">激活</Button>
            <Button size="small" danger :disabled="p.name === 'default' || p.active" @click="deletePreset(p.name)">删除</Button>
          </div>
        </div>
      </div>
    </div>
    <div class="card editor-card">
      <div class="editor-header">
        <span class="muted">{{ editing }}</span>
        <Input v-model="edDesc" placeholder="描述（可选）" style="width:200px" />
        <Button type="primary" @click="activatePreset(editing)">激活</Button>
        <Button @click="savePreset">保存</Button>
      </div>
      <Textarea v-model="edPrompt" placeholder="prompt.txt" :rows="10" />
      <Textarea v-model="edExtra" placeholder="prompt_extra.txt" :rows="10" />
    </div>
  </div>
</template>
