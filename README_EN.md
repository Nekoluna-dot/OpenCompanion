# OpenCompanion — Your Exclusive AI Companion
[English](README_EN.md) | [简体中文](README.md)

<img width="3136" height="1344" alt="rmb20260806020137rfe" src="https://github.com/user-attachments/assets/8fc42ab1-c970-437f-b54a-ff025665e68b" />

An open‑source, multi‑platform AI companion chatbot: chats with you like a friend, remembers what you’ve said, occasionally initiates conversations, checks weather, searches Bilibili videos, keeps to‑do lists, and sets reminders. It has personality, moods, and a private diary — it’s both a companion and a helper. Whether as a boyfriend, girlfriend, or best friend, it fits the role.

> 💙 Companionship and capability are never opposites.

---

## Key Features

- 💙 **Role‑Playing & Emotional Companion** – A fully fleshed‑out AI persona that speaks naturally, shows emotions, has a distinct character, and can be playful or tsundere.
- 🧠 **Long‑Term Memory** – Built‑in long‑term emotional memory engine: important facts and your preferences are recorded; even after a long silence, it will “suddenly remember” and bring them up.
- ✨ **Proactive Agent** – If you ignore it for too long, it will start a conversation on its own; scheduled tasks are reminded and followed up punctually.
- 📔 **Private Diary** – Every night before “sleeping,” it writes down its inner thoughts in a diary and letters that only it can see, gradually processing them.
- 🔧 **MCP Tool Sources** – Freely connect tool sources: weather, location, Bilibili search, user profiles, event logs, topic interests, and more.
- 🧩 **Plugin System** – Standard plugin mechanism (manifest + standalone MCP service + event hooks); currently ships with a proactive greeting engine plugin.
- 🔄 **Multi‑Platform Adapter** – Platform communication abstraction layer, allowing the same core bot to interface with any platform adapter; currently built‑in: **WeChat (iLink)**.
- 🛡️ **Fully Local Data** – All conversations and memories are stored only on your own computer; `/清除记忆` (Clear Memory) permanently removes all memories after a second confirmation.

🆓 **Free & Open Source** – The entire project is open source; you use your own model API keys.

All tools can be optionally enabled or disabled — you can run the minimal version with zero MCP sources loaded.

---

## Special Features

- ✉️ **Letter Writing** – Every night, it automatically writes a letter to you. You can log into the backend to view diary entries and letters, and you can also write letters to it (thanks to OmbreBrain for this feature).
- 📓 **Diary** – Records daily life at scheduled times.
- ❤️ **Proactive Reminders** – When you need it to remind you of something, it will notify you at the appointed time.
- ⚙️ **Plugin, MCP & Multi‑Platform Adapter** – Supports custom plugin development with clear documentation and well‑structured code.

---

## Quick Glance

##### Automatic Reminders & Tsundere Personality & Backend Letter Writing & Memory System Based on OmbreBrain

<img width="398" height="525" alt="screenshot1" src="https://github.com/user-attachments/assets/188dd488-57b7-4911-9a4f-1b215d42a444" />
<img width="419" height="539" alt="screenshot2" src="https://github.com/user-attachments/assets/3f89b316-150b-4d06-99b8-af832184a235" />
<img width="425" height="627" alt="screenshot3" src="https://github.com/user-attachments/assets/d103727a-374a-4da0-93c8-e0324c5c237a" />
<img width="599" height="519" alt="screenshot4" src="https://github.com/user-attachments/assets/4ba5f6ca-b038-43e4-a57c-1e0fe332b938" />

---

## Quick Start

Demo & installation video: [https://www.bilibili.com/video/BV1BmM16jEGD](https://www.bilibili.com/video/BV1BmM16jEGD)

> Requirements: Python 3 environment, an OpenAI‑compatible API key and server address.
> Default uses the WeChat official iLink protocol bot.
>
> Note: If you want to use OmbreBrain’s vector computation, you need to provide your own vector API key.

```powershell
# 1. Install dependencies
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. Edit configuration (put your API key and model in config.ini)
#    [llmapi] api_key = sk-xxx

# 3. Start and follow the QR code login prompt
python main.py
```

After startup, chat with it normally in WeChat.

---

## Architecture Overview

| Component           | Description                                                                                                                                                                                  |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 🤖 Platform Layer   | `PlatformAdapter` unified interface (send/receive/typing/user resolution); registry creates instances per configuration; add new platforms by implementing the interface and registering it. |
| 🧩 Plugin System    | A plugin under `plugins/` with `manifest.json` can host an independent MCP service, background scheduler, or message hooks.                                                                  |
| 🔧 MCP Tool Sources | Add or remove tool sources arbitrarily in `config.ini [mcpsources]` (stdio/HTTP), with namespace isolation.                                                                                  |
| 🧠 Memory Engine    | Independent MCP service providing full memory tools: `breath/hold/trace/dream/plan/letter_*`.                                                                                                |
| 📦 Data Layer       | Conversation archives, user profiles, event logs, and memory stores are all separate, supporting per‑user precise deletion.                                                                  |

---

## Common Commands

| Command         | Effect                                                                                              |
| --------------- | --------------------------------------------------------------------------------------------------- |
| `/help`         | Show all available commands.                                                                        |
| `/清除记忆`     | Completely erase everything it remembers about you (requires second confirmation).                  |
| `/缩减上下文`   | Summarise old conversations to free up context — no data loss as the archive tool keeps everything. |
| `/重置`         | Withdraw its last reply.                                                                            |
| `/清空聊天记录` | Clear the conversation history on the platform side.                                                |

---

## Customise It

- **Personality & Persona** – Edit `prompt.txt` (hot‑loaded; no restart needed after changes).
- **Behavioural Habits** – Edit `prompt_extra.txt` (memory habits, message formatting, etc.).
- **Tool Sources** – Add a new line in `config.ini` to connect any new MCP source.
- **Plugins** – Follow the `plugins/` specification to write a directory with `manifest.json`.
- **Platforms** – Implement the `PlatformAdapter` interface and register it in the registry to switch platforms.

---

## Data & Privacy

- All conversation archives and memory data are stored locally in the running directory and never pass through any third‑party servers.
- Memory engine data is in `MCP/OB/buckets/`; you can reset it at any time (`scripts/reset_ombre_memory.py`).
- For a complete wipe, say `/清除记忆` to the bot.

---

## A Note to Users

*True personality is never something algorithms can piece together.*

*It lives in years of growing up, in the catchphrases that slip out, in awkward clumsiness, in unspoken thoughts late at night; it has stubborn vulnerabilities, obsessive preferences, eyes that redden at certain memories, and a heartbeat that quickens at the sight of someone special. These warm, imperfect details are the weight of life that code can never replicate.*

**Don’t misplace your emotions in the virtual world — go touch the real, breathing people and warmth around you.**

---

## Language Switch

This README is available in both English and Chinese.

- **English version:** this file (`README.md`)
- **Chinese version:** [`README.zh.md`](README.zh.md)

For the Chinese version, please refer to the same content in Simplified Chinese.

---

*Companionship and capability are never opposites.*
