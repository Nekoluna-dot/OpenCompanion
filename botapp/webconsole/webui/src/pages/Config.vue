<script setup>
import { reactive, onMounted } from "vue";
import {
  Button,
  Input,
  Textarea,
  Checkbox,
  Select,
} from "animal-island-ui-vue";
import { api, toast } from "../lib/api.js";

function makeState() {
  return {
    data: null,
    form: {},        // values[sec][key]
    checks: {},      // sec.key -> bool
    sources: [],     // [{name, raw, enabled}]
    descs: {},       // sec.key -> 中文描述
    combo: {},       // key -> 候选项列表
    raw: "",
    rawMode: false,
    models: [],      // model 字段：自动获取到的模型列表
  };
}

const ini = reactive(makeState());
const yaml = reactive(makeState());

// model 字段支持「自动获取」：从后端拉取可用模型列表，供下拉选择
const isModelField = (key) => key === "model";
const fetching = reactive({}); // "sec.key" -> 是否请求中

function modelOptions(state, sec, key) {
  const list = (state.models || []).slice();
  const cur = (state.form[sec] || {})[key];
  if (cur && !list.includes(cur)) list.unshift(cur); // 保留当前值，避免被覆盖
  return list.map((m) => ({ label: m, value: m }));
}

async function fetchModels(state, sec, key) {
  const tag = sec + "." + key;
  const baseUrl = ((state.form[sec] || {}).base_url || "").trim();
  if (!baseUrl) { toast("请先填写 base_url（API 地址）", "err"); return; }
  const apiKey = ((state.form[sec] || {}).api_key || "").trim();
  fetching[tag] = true;
  try {
    const r = await api("/api/llm/models", "POST", { base_url: baseUrl, api_key: apiKey });
    if (r && r.ok) {
      state.models = r.models || [];
      toast("获取到 " + state.models.length + " 个模型", "ok");
    } else {
      toast("获取失败：" + ((r && r.error) || "未知错误"), "err");
    }
  } catch (e) {
    toast(e.message, "err");
  } finally {
    fetching[tag] = false;
  }
}

function applyData(state, d) {
  state.data = d;
  const values = d.values || {};
  const schema = d.schema || {};
  const form = {};
  const checks = {};
  for (const sec of Object.keys(schema)) {
    form[sec] = {};
    for (const key of Object.keys(schema[sec])) {
      const type = schema[sec][key];
      const val = (values[sec] || {})[key];
      if (type === "bool") {
        checks[sec + "." + key] = String(val).toLowerCase() === "true" || val === "1" || val === "on";
      } else {
        form[sec][key] = val != null ? String(val) : "";
      }
    }
  }
  state.form = form;
  state.checks = checks;
  state.sources = (d.sources || []).map(s => ({ name: s.name, raw: s.raw, enabled: !!s.enabled }));
  state.descs = d.descs || {};
  state.combo = d.combo || {};
  state.raw = d.raw || "";
  state.models = [];
}

function collectValues(state) {
  const values = {};
  const schema = (state.data && state.data.schema) || {};
  for (const sec of Object.keys(schema)) {
    values[sec] = {};
    for (const key of Object.keys(schema[sec])) {
      const type = schema[sec][key];
      if (type === "bool") values[sec][key] = state.checks[sec + "." + key] ? "true" : "false";
      else values[sec][key] = (state.form[sec][key] || "").trim();
    }
  }
  return values;
}

async function loadIni() {
  try { applyData(ini, await api("/api/config/ini")); }
  catch (e) { toast(e.message, "err"); }
}
async function loadYaml() {
  try { applyData(yaml, await api("/api/config/yaml")); }
  catch (e) { toast(e.message, "err"); }
}

async function restartBot() {
  try { const r = await api("/api/bot/restart", "POST", {}); toast(r.result, r.result === "ok" ? "ok" : "err"); }
  catch (e) { toast(e.message, "err"); }
}

async function saveIni(restart) {
  try {
    const payload = ini.rawMode
      ? { raw: ini.raw }
      : { values: collectValues(ini), sources: ini.sources.map(s => ({ name: s.name, raw: s.raw, enabled: s.enabled })) };
    await api("/api/config/ini", "POST", payload);
    toast("config.ini 已保存", "ok");
    if (restart) await restartBot();
  } catch (e) { toast(e.message, "err"); }
}
async function saveYaml(restart) {
  try {
    const payload = yaml.rawMode ? { raw: yaml.raw } : { values: collectValues(yaml) };
    await api("/api/config/yaml", "POST", payload);
    toast("config.yaml 已保存", "ok");
    if (restart) await restartBot();
  } catch (e) { toast(e.message, "err"); }
}

onMounted(() => { loadIni(); loadYaml(); });
</script>

<template>
  <div class="grid cols-2">
    <div class="card">
      <div class="card-title">机器人配置（config.ini）</div>
      <div class="row">
        <Button @click="loadIni">重新读取</Button>
        <Button type="primary" @click="saveIni(false)">保存</Button>
        <Button type="primary" @click="saveIni(true)">保存并重启机器人</Button>
        <Checkbox v-model:checked="ini.rawMode">编辑原始文本</Checkbox>
      </div>
      <div v-show="!ini.rawMode">
        <template v-if="ini.data && ini.data.schema">
          <fieldset v-for="(keys, sec) in ini.data.schema" :key="sec">
            <legend>{{ sec }}</legend>
            <div v-for="(type, key) in keys" :key="key" class="fld">
              <span>
                {{ key }}
                <i v-if="(ini.descs[sec] || {})[key]" class="hint" :title="ini.descs[sec][key]">{{ ini.descs[sec][key] }}</i>
              </span>
              <Checkbox v-if="type === 'bool'" v-model:checked="ini.checks[sec + '.' + key]" />
              <Select v-else-if="type === 'combo'"
                      v-model="ini.form[sec][key]"
                      :options="((ini.combo || {})[key] || []).map(o => ({ label: o, value: o }))" />
              <div v-else-if="isModelField(key)" class="model-row">
                <Input :type="type === 'password' ? 'password' : 'text'" v-model="ini.form[sec][key]"
                       placeholder="手动填写，或点右侧自动获取" />
                <Button size="small" :loading="!!fetching[sec + '.' + key]"
                        @click="fetchModels(ini, sec, key)">自动获取</Button>
                <Select v-model="ini.form[sec][key]" :options="modelOptions(ini, sec, key)"
                        placeholder="获取后下拉选择" />
              </div>
              <Input v-else :type="type === 'password' ? 'password' : 'text'" v-model="ini.form[sec][key]" />
            </div>
          </fieldset>
          <fieldset v-if="ini.sources.length">
            <legend>[mcpsources] 外部 MCP 工具源（勾选 = 启用）</legend>
            <div v-for="s in ini.sources" :key="s.name" class="fld">
              <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ s.name }} = {{ s.raw }}</span>
              <Checkbox v-model:checked="s.enabled" />
            </div>
          </fieldset>
        </template>
      </div>
      <Textarea v-show="ini.rawMode" v-model="ini.raw" :rows="18" class="config-raw" />
    </div>

    <div class="card">
      <div class="card-title">OmbreBrain 配置（MCP/OB/config.yaml）</div>
      <div class="row">
        <Button @click="loadYaml">重新读取</Button>
        <Button type="primary" @click="saveYaml(false)">保存</Button>
        <Button type="primary" @click="saveYaml(true)">保存并重启机器人</Button>
        <Checkbox v-model:checked="yaml.rawMode">编辑原始文本</Checkbox>
      </div>
      <div v-show="!yaml.rawMode">
        <template v-if="yaml.data && yaml.data.schema">
          <fieldset v-for="(keys, sec) in yaml.data.schema" :key="sec">
            <legend>{{ sec }}</legend>
            <div v-for="(type, key) in keys" :key="key" class="fld">
              <span>
                {{ key }}
                <i v-if="(yaml.descs[sec] || {})[key]" class="hint" :title="yaml.descs[sec][key]">{{ yaml.descs[sec][key] }}</i>
              </span>
              <Checkbox v-if="type === 'bool'" v-model:checked="yaml.checks[sec + '.' + key]" />
              <Select v-else-if="type === 'combo'"
                      v-model="yaml.form[sec][key]"
                      :options="((yaml.combo || {})[key] || []).map(o => ({ label: o, value: o }))" />
              <div v-else-if="isModelField(key)" class="model-row">
                <Input :type="type === 'password' ? 'password' : 'text'" v-model="yaml.form[sec][key]"
                       placeholder="手动填写，或点右侧自动获取" />
                <Button size="small" :loading="!!fetching[sec + '.' + key]"
                        @click="fetchModels(yaml, sec, key)">自动获取</Button>
                <Select v-model="yaml.form[sec][key]" :options="modelOptions(yaml, sec, key)"
                        placeholder="获取后下拉选择" />
              </div>
              <Input v-else :type="type === 'password' ? 'password' : 'text'" v-model="yaml.form[sec][key]" />
            </div>
          </fieldset>
        </template>
      </div>
      <Textarea v-show="yaml.rawMode" v-model="yaml.raw" :rows="18" class="config-raw" />
    </div>
  </div>
</template>
