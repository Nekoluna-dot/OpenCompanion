import json
import math
import random
import re
import threading
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("revive")

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
REVIVE_DIR = DATA_DIR / "revive"
CONFIG_PATH = DATA_DIR / "revive_config.json"
_lock = threading.Lock()

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_STATES = ["chatting", "idle", "busy", "sleeping", "away", "needing"]

STATE_ZH = {
    "chatting": "聊天中",
    "idle": "空闲",
    "busy": "忙碌",
    "sleeping": "睡觉",
    "away": "离开",
    "needing": "需要关心",
}
"""
数据文件目录:data/revive/{user_id}.json
写在前面 啥事效用 你可以理解为熵的相反 一个是无价值性 一个是有价值性
因此下面的代码通过判断有没有价值来决策是否触发主动问候
"""
DEFAULT_CONFIG = {
    "lambda_rate": 0.30,              # 基础渴望速率（事件/小时）——均衡档
    "check_interval_minutes": 5,      # 掷骰频率（分钟）：5 分钟一次
    "growth_factor": 0.12,            # 渴望增长步长——均衡档
    "max_probability": 0.95,          # 渴望上限
    "min_interval_hours": 0.15,        # 反骚扰冷却：发过一次后至少 1 小时不再主动
    "infogain_threshold": 0.20,       # 信息增益比率阈值
    "infogain_min_gain": 0.1,         # 最小绝对增益
    "infogain_decay": 0.35,           # 连续未回复衰减
    # "min_silence_minutes": 30,      # 最小沉默时长硬门槛 见 _infogain
    "bayesian_threshold": 0.35,       # 发送效用阈值——均衡档
    "quiet_hours_start": "05:00",     # 安静时段（默认兜底，会被夜猫子学习豁免）
    "quiet_hours_end": "08:00",
    "quiet_activity_threshold": 3,    # 安静时段内活跃观测 ≥ N 条 → 视为夜猫子，不再硬拦截
    "normal_send_probability": 0.7,   # 普通时段发送概率
}

DEFAULT_TRANSITIONS = {
    "chatting": {"chatting": 0.5, "idle": 0.3, "busy": 0.1, "sleeping": 0.0, "away": 0.05, "needing": 0.05},
    "idle": {"chatting": 0.15, "idle": 0.4, "busy": 0.2, "sleeping": 0.05, "away": 0.1, "needing": 0.1},
    "busy": {"chatting": 0.05, "idle": 0.2, "busy": 0.5, "sleeping": 0.1, "away": 0.1, "needing": 0.05},
    "sleeping": {"chatting": 0.02, "idle": 0.1, "busy": 0.08, "sleeping": 0.7, "away": 0.05, "needing": 0.05},
    "away": {"chatting": 0.05, "idle": 0.15, "busy": 0.15, "sleeping": 0.15, "away": 0.4, "needing": 0.1},
    "needing": {"chatting": 0.1, "idle": 0.15, "busy": 0.1, "sleeping": 0.05, "away": 0.1, "needing": 0.5},
}

# 各状态发送效用
SEND_UTILITY = {
    "chatting": 0.2,
    "idle": 0.7,
    "busy": 0.1,
    "sleeping": 0.0,
    "away": 0.3,
    "needing": 0.9,
}

# 初始信念分布
DEFAULT_PRIOR = {
    "chatting": 0.1,
    "idle": 0.2,
    "busy": 0.3,
    "sleeping": 0.1,
    "away": 0.2,
    "needing": 0.1,
}

# 默认似然参数 其实就是默认清情况的概率
_SPEED_PROFILE = {"chatting": (0.8, 0.15), "idle": (0.5, 0.2), "busy": (0.2, 0.15),
                  "sleeping": (0.0, 0.05), "away": (0.1, 0.1), "needing": (0.3, 0.2)}
_LENGTH_PROFILE = {"chatting": (0.7, 0.15), "idle": (0.4, 0.2), "busy": (0.15, 0.1),
                   "sleeping": (0.0, 0.05), "away": (0.1, 0.1), "needing": (0.3, 0.2)}
_SILENCE_PROFILE = {"chatting": (0.5, 1.0), "idle": (2.0, 2.0), "busy": (4.0, 3.0),
                    "sleeping": (8.0, 3.0), "away": (12.0, 6.0), "needing": (24.0, 12.0)}
_HOUR_WINDOWS = {
    "chatting": [(9, 12), (17, 22)],
    "idle": [(8, 12), (14, 18), (19, 23)],
    "busy": [(9, 12), (13, 17)],
    "sleeping": [(0, 7), (23, 24)],
    "away": [(0, 24)],
    "needing": [(10, 12), (15, 18), (20, 23)],
}


# ── 基础工具 ──────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime(_TIME_FORMAT)


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, _TIME_FORMAT)


def _sanitize_user_id(user_id: str) -> str:
    uid = (user_id or "").split("@", 1)[0].strip()
    uid = _INVALID_CHARS.sub("_", uid)
    if not uid or uid in (".", ".."):
        raise ValueError(f"非法用户 ID: {user_id!r}")
    return uid


def _user_file(user_id: str) -> Path:
    return REVIVE_DIR / f"{_sanitize_user_id(user_id)}.json"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg = dict(DEFAULT_CONFIG)
            cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
            return cfg
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_CONFIG)


def _save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def _load_state(user_id: str) -> dict:
    path = _user_file(user_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_state(user_id: str, state: dict) -> None:
    path = _user_file(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _new_state(cfg: dict) -> dict:
    return {
        "probability": _base_probability(cfg),
        "last_tick_time": None,
        "last_send_time": None,
        "last_user_reply": None,
        "miss_streak": 0,
        "my_unanswered": 0,
        "belief": dict(DEFAULT_PRIOR),
        "last_reply_speed": 0.5,
        "last_reply_length": 0.5,
        "recent_messages": [],
        "log": [],
        "observations": [],
        "learned": {},
        "created_at": _now(),
        "updated_at": _now(),
    }


def _gaussian(x: float, mean: float, std: float) -> float:
    if std <= 0:
        return 1.0 if abs(x - mean) < 0.01 else 0.01
    return math.exp(-0.5 * ((x - mean) / std) ** 2)


def _base_probability(cfg: dict) -> float:
    lam = cfg["lambda_rate"]
    t = cfg["check_interval_minutes"] / 60.0
    return 1 - math.exp(-lam * t)


def _parse_hour(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and ":" in value:
        h, m = value.split(":")
        return int(h) + int(m) / 60.0
    return float(value)


def _hour_of(now: datetime) -> float:
    return now.hour + now.minute / 60.0


#贝叶斯部分 不断修正概率

class StateEstimator:

    def __init__(self, belief: dict, learned: dict):
        self._STATES = list(_STATES)
        self._belief = {k: float(v) for k, v in belief.items()}
        self._learned = learned or {}

    @property
    def belief(self) -> dict:
        return dict(self._belief)

    def _transitions(self) -> dict:
        return self._learned.get("transitions") or DEFAULT_TRANSITIONS

    def _likelihood(self, key: str, state: str) -> tuple:
        if self._learned.get("likelihoods", {}).get(state, {}).get(key):
            return tuple(self._learned["likelihoods"][state][key])
        return {
            "reply_speed": _SPEED_PROFILE,
            "reply_length": _LENGTH_PROFILE,
            "silence_hours": _SILENCE_PROFILE,
        }[key][state]

    def _temporal(self, state: str) -> dict:
        return self._learned.get("temporal", {}).get(state)

    def _transition(self) -> None:
        new_belief = {s: 0.0 for s in _STATES}
        for cur in _STATES:
            for nxt in _STATES:
                new_belief[nxt] += self._belief[cur] * self._transitions()[cur][nxt]
        self._belief = new_belief

    def _likelihood_hour(self, hour: float, state: str) -> float:
        temporal = self._temporal(state)
        if temporal and int(hour) % 24 in temporal:
            return temporal[int(hour) % 24]
        for start, end in _HOUR_WINDOWS[state]:
            if start <= hour < end:
                return 1.0
        return 0.1

    def update(self, reply_speed=None, reply_length=None, hour=None,
               silence_hours=None) -> None:
        """P(state|obs) ∝ P(obs|state) × P(state)。"""
        self._transition()
        likelihoods = {s: 1.0 for s in _STATES}
        if reply_speed is not None:
            for s in _STATES:
                m, sd = self._likelihood("reply_speed", s)
                likelihoods[s] *= _gaussian(reply_speed, m, sd)
        if reply_length is not None:
            for s in _STATES:
                m, sd = self._likelihood("reply_length", s)
                likelihoods[s] *= _gaussian(reply_length, m, sd)
        if hour is not None:
            for s in _STATES:
                likelihoods[s] *= self._likelihood_hour(hour, s)
        if silence_hours is not None:
            for s in _STATES:
                m, sd = self._likelihood("silence_hours", s)
                likelihoods[s] *= _gaussian(silence_hours, m, sd)
        unnormalized = {s: likelihoods[s] * self._belief[s] for s in _STATES}
        total = sum(unnormalized.values())
        if total > 0:
            self._belief = {k: v / total for k, v in unnormalized.items()}

    def most_likely(self) -> tuple:
        best = max(self._STATES, key=lambda s: self._belief[s])
        return best, self._belief[best]

    def send_utility(self) -> float:
        return sum(self._belief[s] * SEND_UTILITY[s] for s in _STATES)



def _infogain(state: dict, cfg: dict, now: datetime, hour: float) -> dict:
    """三个信息源：沉默时长 / 对话流 / 消息熵值"""
    last_reply = state.get("last_user_reply")
    silence_hours = 48.0
    if last_reply:
        silence_hours = (now - _parse_time(last_reply)).total_seconds() / 3600.0


    #     DEFAULT_CONFIG 里的 min_silence_minutes。
    # min_silence = cfg["min_silence_minutes"] / 60.0
    # if last_reply and silence_hours < min_silence:
    #     return {
    #         "worth": False,
    #         "gain": 0.0,
    #         "ratio": 0.0,
    #         "silence_hours": silence_hours,
    #         "entropy": 0.0,
    #         "reason": f"沉默仅 {silence_hours*60:.0f} 分钟（< 最小 {cfg['min_silence_minutes']} 分钟）",
    #     }
    e1 = min(1.0, silence_hours / 12.0)
    if silence_hours < 0.5:
        r1 = 0.1
    elif silence_hours < 2:
        r1 = 0.3
    elif silence_hours < 8:
        r1 = 0.6
    else:
        r1 = 0.8

    # 对话流源：活跃对话 / 等待回复 / 沉睡
    replied_recent = silence_hours < 1.0
    unanswered = state.get("my_unanswered", 0)
    if replied_recent:
        e2, r2 = 0.2, 0.3
    elif unanswered > 0:
        e2 = 0.4
        r2 = 0.1 if unanswered >= 3 else 0.3
    else:
        e2, r2 = 0.7, 0.7

    # 判断之前有没有对话 如果有 那么默认值得对话的评价下降 没有就高些
    recent = state.get("recent_messages", [])
    e3 = 0.5
    r3 = 0.8 if not recent else 0.7

    total_entropy = e1 + e2 + e3
    total_resolution = e1 * r1 + e2 * r2 + e3 * r3
    decay = cfg["infogain_decay"] ** unanswered
    gain = total_resolution * decay
    ratio = gain / total_entropy if total_entropy > 0 else 0.0
    worth = ratio >= cfg["infogain_threshold"] and gain >= cfg["infogain_min_gain"]
    return {
        "worth": worth,
        "gain": gain,
        "ratio": ratio,
        "silence_hours": silence_hours,
        "entropy": total_entropy,
    }


def _is_night_owl(state: dict, cfg: dict) -> tuple:

    start = _parse_hour(cfg["quiet_hours_start"])
    end = _parse_hour(cfg["quiet_hours_end"])
    obs = state.get("observations", [])
    active_states = {"chatting", "idle", "needing"}
    quiet_active = 0
    for o in obs:
        h = o.get("hour")
        if h is None or o.get("state") not in active_states:
            continue
        if start <= h % 24 < end:
            quiet_active += 1
    threshold = int(cfg["quiet_activity_threshold"])
    if quiet_active >= threshold:
        return True, f"夜猫子学习：有用数据{quiet_active} 条 ≥ {threshold}"
    return False, f"非夜猫子：有用数据{quiet_active} 条 < {threshold}"


def _adjudicate(cfg: dict, hour: float, night_owl: bool = False) -> tuple:
    start = _parse_hour(cfg["quiet_hours_start"])
    end = _parse_hour(cfg["quiet_hours_end"])
    if start <= hour < end:
        if night_owl:
            return True, f"安静时段已解除 下一步决策 ({_fmt_hour(hour)})"
        return False, f"安静时段 ({_fmt_hour(hour)})"
    if random.random() < cfg["normal_send_probability"]:
        return True, f"普通时段，可以发送 ({_fmt_hour(hour)})"
    return False, f"决策结果 不合适 ({_fmt_hour(hour)})"


def _engine_tick(state: dict, cfg: dict, now: datetime, hour: float) -> dict:
    """引擎单次掷骰：min_interval 冷却 → 泊松骰子 → 裁决。"""
    last_send = state.get("last_send_time")
    if last_send:
        elapsed = (now - _parse_time(last_send)).total_seconds() / 3600.0
        if elapsed < cfg["min_interval_hours"]:
            return {"action": "skip", "probability": state["probability"],
                    "reason": f"冷却中 (t={elapsed:.2f}h < {cfg['min_interval_hours']}h)"}

    roll = random.random() #扔骰子
    hit = roll < state["probability"] #哎呀 其实就是抽卡 越抽概率越大 但有不太一样的是ys抽卡概率是固定的 除了到70抽以上 所以可以说这里是70抽以上的
    if not hit:
        state["probability"] = min(state["probability"] + cfg["growth_factor"], cfg["max_probability"])
        state["miss_streak"] += 1
        return {"action": "miss", "probability": state["probability"], "roll": roll}

    send, reason = _adjudicate(cfg, hour, night_owl=_is_night_owl(state, cfg)[0])
    if send:
        return {"action": "send", "probability": state["probability"], "roll": roll, "reason": reason}
    state["probability"] = min(state["probability"] + cfg["growth_factor"], cfg["max_probability"])
    state["miss_streak"] += 1
    return {"action": "hold", "probability": state["probability"], "roll": roll, "reason": reason}


def _fmt_hour(h: float) -> str:
    return f"{int(h):02d}:{int((h % 1) * 60):02d}"


def _build_prompt(state: dict, user_state: str, probability: float, hour: float,
                  utility: float) -> str:
    h = int(hour)
    if 6 <= h < 10:
        ctx = "早晨"
    elif 11 <= h < 14:
        ctx = "中午"
    elif 14 <= h < 18:
        ctx = "下午"
    elif 18 <= h < 22:
        ctx = "傍晚"
    else:
        ctx = "深夜"
    return (
        f"[主动问候] 时间 {_fmt_hour(hour)} ({ctx})，推测状态: {STATE_ZH.get(user_state, user_state)}，"
        f"发送效用 {utility:.0%}，渴望度 {probability:.0%}，"
        f"连续沉默/未回复 {state.get('miss_streak', 0)} 次"
    )


def _do_tick(user_id: str, hour: float | None = None, force: bool = False) -> dict:

    cfg = _load_config()
    now = datetime.now()
    cur_hour = hour if hour is not None else _hour_of(now)

    state = _load_state(user_id) or _new_state(cfg)
    estimator = StateEstimator(state["belief"], state.get("learned"))

    last_tick = state.get("last_tick_time")
    if last_tick and not force:
        elapsed_min = (now - _parse_time(last_tick)).total_seconds() / 60.0
        if elapsed_min < cfg["check_interval_minutes"] * 0.9:
            return {
                "should_send": False,
                "stage": "cooldown",
                "action": "skip",
                "user_state": "unknown",
                "user_state_zh": "未知",
                "state_confidence": 0,
                "send_utility": 0,
                "probability": state["probability"],
                "info_gain": 0,
                "prompt": "",
                "reason": f"距上次 tick  {elapsed_min:.0f} 分钟（< {cfg['check_interval_minutes']}）",
            }#相当于冷静期
    state["last_tick_time"] = _now()

    # 1：泊松骰子
    if not force:
        tick = _engine_tick(state, cfg, now, cur_hour)
        if tick["action"] not in ("send",):
            state["log"].append({"time": _now(), "action": tick["action"],
                                 "probability": tick["probability"], "reason": tick.get("reason", "")})
            _trim(state)
            _save_state(user_id, state)
            return {
                "should_send": False,
                "stage": "poisson",
                "action": tick["action"],
                "user_state": "unknown",
                "user_state_zh": "未知",
                "state_confidence": 0,
                "send_utility": 0,
                "probability": tick["probability"],
                "info_gain": 0,
                "prompt": "",
                "reason": f"Poisson: {tick['action']} {tick.get('reason', '')}",
            }

    # 2：信息增益
    ig = _infogain(state, cfg, now, cur_hour)
    if not ig["worth"]:
        ig_reason = ig.get("reason", f"gain={ig['gain']:.3f}, ratio={ig['ratio']:.0%}")
        state["log"].append({"time": _now(), "action": "hold",
                             "probability": state["probability"],
                             "reason": f"信息增益不足 ({ig_reason})"})
        _trim(state)
        _save_state(user_id, state)
        return {
            "should_send": False,
            "stage": "infogain",
            "action": "hold",
            "user_state": "unknown",
            "user_state_zh": "未知",
            "state_confidence": 0,
            "send_utility": 0,
            "probability": state["probability"],
            "info_gain": ig["gain"],
            "prompt": "",
            "reason": f"InfoGain: {ig_reason}，值不值得发",
        }

    # 3：贝叶斯状态推断
    silence_hours = ig["silence_hours"]
    estimator.update(reply_speed=state.get("last_reply_speed", 0.5),
                     reply_length=state.get("last_reply_length", 0.5),
                     hour=cur_hour, silence_hours=silence_hours)
    best_state, confidence = estimator.most_likely()
    utility = estimator.send_utility()

    if utility < cfg["bayesian_threshold"]:
        state["log"].append({"time": _now(), "action": "hold",
                             "probability": state["probability"],
                             "reason": f"状态={best_state} 效用={utility:.2f} < {cfg['bayesian_threshold']}"})
        state["belief"] = estimator.belief
        _trim(state)
        _save_state(user_id, state)
        return {
            "should_send": False,
            "stage": "bayesian",
            "action": "hold",
            "user_state": best_state,
            "user_state_zh": STATE_ZH.get(best_state, best_state),
            "state_confidence": confidence,
            "send_utility": utility,
            "probability": state["probability"],
            "info_gain": ig["gain"],
            "prompt": "",
            "reason": f"Bayesian: 效用 {utility:.2f} < 阈值 {cfg['bayesian_threshold']} ({STATE_ZH.get(best_state, best_state)})",
        }

    # 全部通过后确认发送然后重置渴望度
    state["probability"] = _base_probability(cfg)
    state["miss_streak"] = 0
    state["last_send_time"] = _now()
    state["belief"] = estimator.belief
    state["log"].append({"time": _now(), "action": "send",
                         "probability": state["probability"],
                         "reason": f"状态={best_state} 效用={utility:.2f}"})
    _trim(state)
    _save_state(user_id, state)
    return {
        "should_send": True,
        "stage": "full",
        "action": "send",
        "user_state": best_state,
        "user_state_zh": STATE_ZH.get(best_state, best_state),
        "state_confidence": confidence,
        "send_utility": utility,
        "probability": state["probability"],
        "info_gain": ig["gain"],
        "silence_hours": ig["silence_hours"],
        "prompt": _build_prompt(state, best_state, state["probability"], cur_hour, utility),
        "reason": f"发送 (状态={STATE_ZH.get(best_state, best_state)}, 效用={utility:.2f})",
    }


def _trim(state: dict, log_max: int = 200, obs_max: int = 400) -> None:
    state["log"] = state.get("log", [])[-log_max:]
    state["observations"] = state.get("observations", [])[-obs_max:]


def _learn(state: dict) -> dict:
    """从观测历史学习：转移矩阵 / 似然参数 / 时间模式。"""
    obs = state.get("observations", [])
    learned = {"transitions": None, "likelihoods": None, "temporal": None}

    # 1. 转移矩阵（add-1 平滑）
    if len(obs) >= 20:
        counts = {f: {t: 0 for t in _STATES} for f in _STATES}
        for i in range(len(obs) - 1):
            f, t = obs[i].get("state"), obs[i + 1].get("state")
            if f in counts and t in counts[f]:
                counts[f][t] += 1
        transitions = {}
        for f in _STATES:
            total = sum(counts[f].values())
            transitions[f] = {
                t: (counts[f][t] + 1) / (total + len(_STATES)) for t in _STATES
            }
        learned["transitions"] = transitions

    # 2. 似然参数（均值/方差，每状态至少 5 条）
    likelihoods = {}
    for s in _STATES:
        pool = [o for o in obs if o.get("state") == s]
        likelihoods[s] = {}
        for key in ("reply_speed", "reply_length", "silence_hours"):
            values = [o[key] for o in pool if o.get(key) is not None]
            if len(values) >= 5:
                mean = sum(values) / len(values)
                var = sum((x - mean) ** 2 for x in values) / len(values)
                std = max(0.05, min(0.5, math.sqrt(var) if var > 0 else 0.1))
                likelihoods[s][key] = [round(mean, 4), round(std, 4)]
    if any(likelihoods[s] for s in _STATES):
        learned["likelihoods"] = likelihoods

    # 3. 时间模式 P(state | hour)（add-1 平滑）
    temporal = {}
    hour_totals = {h: 0 for h in range(24)}
    for o in obs:
        h = int(o.get("hour", 0)) % 24
        hour_totals[h] += 1
    for s in _STATES:
        temporal[s] = {}
        for h in range(24):
            count = sum(1 for o in obs if o.get("state") == s and int(o.get("hour", 0)) % 24 == h)
            total = hour_totals[h]
            temporal[s][h] = (count + 1) / (total + len(_STATES)) if total > 0 else 1.0 / len(_STATES)
    learned["temporal"] = temporal

    state["learned"] = {k: v for k, v in learned.items() if v is not None}
    return state["learned"]


# ── MCP 工具 ─────────────────────────────────────────────

@mcp.tool()
def love_tick(user_id: str, hour: float | None = None) -> dict:
    """
    这里要改代码的小猫娘们注意了 这个MCP工具是不映射的 只是为了跨进程通信
    因为这个是独立进程 刚好是stdio来通信 
    """
    return _do_tick(user_id, hour)


# ── 调试工具：已注释（不注册为 MCP 工具，不暴露给 LLM，也不允许调用）──
# @mcp.tool()
def love_trigger(user_id: str, hour: float | None = None) -> dict:
    """Force a proactive-greeting decision (simulated trigger).

    Skips the Poisson roll (cooldown + random timing) as if the engine
    decided "this is the moment", then still runs the real InfoGain and
    Bayesian stages. If the user is genuinely not worth disturbing right
    now (low info gain or low send utility), returns should_send=False —
    so this is NOT a guaranteed send, just a deterministic timing check.

    Used for debugging / manual testing from the bot console.

    Args:
        user_id: The current conversation user ID.
        hour: Optional hour override (0-24) for testing; omit to use now.
    """
    return _do_tick(user_id, hour, force=True)


@mcp.tool()
def love_record_reply(user_id: str, reply_speed: float = 0.5,
                      reply_length: float = 0.5, message: str = "") -> dict:
    """Record that the user replied (feeds the Bayesian estimator).

    Call right after the user answers a proactive or normal message. The
    reply speed (0-1, fast=1) and reply length (0-1, long=1) update the
    inferred user state and are collected for online learning.

    Args:
        user_id: The current conversation user ID.
        reply_speed: How fast the user replied, 0-1. Default 0.5.
        reply_length: How long the reply was, 0-1. Default 0.5.
        message: Optional reply text for novelty tracking.
    """
    uid = _sanitize_user_id(user_id)
    cfg = _load_config()
    with _lock:
        state = _load_state(uid) or _new_state(cfg)
        now = datetime.now()
        state["last_user_reply"] = _now()
        state["my_unanswered"] = 0
        state["last_reply_speed"] = max(0.0, min(1.0, reply_speed))
        state["last_reply_length"] = max(0.0, min(1.0, reply_length))
        if message:
            state["recent_messages"] = (state.get("recent_messages", []) + [message])[-20:]

        estimator = StateEstimator(state["belief"], state.get("learned"))
        estimator.update(reply_speed=state["last_reply_speed"],
                         reply_length=state["last_reply_length"],
                         hour=_hour_of(now), silence_hours=0.0)
        state["belief"] = estimator.belief
        best, conf = estimator.most_likely()

        # 学习：记录观测，攒够 20 条自动更新参数
        state["observations"] = (state.get("observations", []) +
                                 [{"state": best, "reply_speed": state["last_reply_speed"],
                                   "reply_length": state["last_reply_length"],
                                   "silence_hours": 0.0, "hour": _hour_of(now)}])[-400:]
        if len(state["observations"]) % 20 == 0 and len(state["observations"]) >= 20:
            _learn(state)
        _save_state(uid, state)
    return {
        "inferred_state": best,
        "inferred_state_zh": STATE_ZH.get(best, best),
        "confidence": round(conf, 4),
        "learned_params": bool(state.get("learned")),
        "observations": len(state.get("observations", [])),
    }


@mcp.tool()
def love_record_send(user_id: str, message: str = "") -> dict:
    """Record that we sent a message to the user (track unanswered count).

    Call after a proactive message is actually delivered. Tracks how many
    of our messages the user has not replied to, which lowers the info-gain
    decay (sending more without reply becomes less worthwhile).

    Args:
        user_id: The current conversation user ID.
        message: Optional message text for novelty tracking.
    """
    uid = _sanitize_user_id(user_id)
    cfg = _load_config()
    with _lock:
        state = _load_state(uid) or _new_state(cfg)
        state["my_unanswered"] = state.get("my_unanswered", 0) + 1
        if message:
            state["recent_messages"] = (state.get("recent_messages", []) + [message])[-20:]
        _save_state(uid, state)
    return {"my_unanswered": state["my_unanswered"]}


# ── 调试工具：已注释（不注册为 MCP 工具，不暴露给 LLM，也不允许调用）──
# @mcp.tool()
def love_state(user_id: str) -> dict:
    """Inspect the current engagement state for a user.

    Returns the longing probability, inferred user state distribution, send
    utility, last activity timestamps and recent decision log. Use this to
    check why the engine is / isn't reaching out.

    Args:
        user_id: The current conversation user ID.
    """
    uid = _sanitize_user_id(user_id)
    cfg = _load_config()
    with _lock:
        state = _load_state(uid) or _new_state(cfg)
        estimator = StateEstimator(state["belief"], state.get("learned"))
        best, conf = estimator.most_likely()
        return {
            "probability": round(state["probability"], 4),
            "base_probability": round(_base_probability(cfg), 4),
            "miss_streak": state.get("miss_streak", 0),
            "my_unanswered": state.get("my_unanswered", 0),
            "last_send_time": state.get("last_send_time"),
            "last_user_reply": state.get("last_user_reply"),
            "belief": {k: round(v, 4) for k, v in state["belief"].items()},
            "most_likely_state": best,
            "most_likely_state_zh": STATE_ZH.get(best, best),
            "confidence": round(conf, 4),
            "send_utility": round(estimator.send_utility(), 4),
            "learned_params": bool(state.get("learned")),
            "observations": len(state.get("observations", [])),
            "recent_log": list(reversed(state.get("log", [])[-10:])),
        }


# ── 调试工具：已注释（不注册为 MCP 工具，不暴露给 LLM，也不允许调用）──
# @mcp.tool()
def love_insights(user_id: str) -> str:
    """Learned user behavior insights (after enough observations).

    Summarizes what the learner discovered: most common state, peak hours
    per state, and frequent state transitions. Returns a short Chinese text;
    "数据不足" if the learner has fewer than 20 observations.

    Args:
        user_id: The current conversation user ID.
    """
    uid = _sanitize_user_id(user_id)
    with _lock:
        state = _load_state(uid)
    if not state or len(state.get("observations", [])) < 20:
        return "数据不足（至少需要 20 条观测）"
    learned = _learn(state)
    with _lock:
        _save_state(uid, state)

    obs = state["observations"]
    state_counts = {}
    for o in obs:
        state_counts[o.get("state")] = state_counts.get(o.get("state"), 0) + 1
    most = max(state_counts, key=state_counts.get) if state_counts else "unknown"

    peak = {}
    hour_counts = {}
    for o in obs:
        h = int(o.get("hour", 0)) % 24
        s = o.get("state")
        hour_counts.setdefault(s, {})
        hour_counts[s][h] = hour_counts[s].get(h, 0) + 1
    for s, counts in hour_counts.items():
        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:3]
        peak[s] = [h for h, _ in top]

    lines = [f"总观测 {len(obs)} 条，最常出现状态: {STATE_ZH.get(most, most)}"]
    for s, hours in peak.items():
        lines.append(f"  {STATE_ZH.get(s, s)} 常见时段: {', '.join(f'{h:02d}点' for h in sorted(hours))}")
    return "\n".join(lines)


# ── 调试工具：已注释（不注册为 MCP 工具，不暴露给 LLM，也不允许调用）──
# @mcp.tool()
def love_reset(user_id: str) -> str:
    """Reset a user's engagement state (belief, longing, log, learned).

    Args:
        user_id: The current conversation user ID.
    """
    uid = _sanitize_user_id(user_id)
    cfg = _load_config()
    with _lock:
        state = _new_state(cfg)
        _save_state(uid, state)
    return "已重置"


# ── 调试工具：已注释（不注册为 MCP 工具，不暴露给 LLM，也不允许调用）──
# @mcp.tool()
def love_config() -> dict:
    """View the current engagement engine configuration.

    Returns lambda_rate, check interval, growth factor, thresholds and
    quiet hours. Use before deciding whether the engine behaves as wanted.
    """
    return _load_config()


# ── 调试工具：已注释（不注册为 MCP 工具，不暴露给 LLM，也不允许调用）──
# @mcp.tool()
def love_configure(lambda_rate: float | None = None,
                   check_interval_minutes: int | None = None,
                   growth_factor: float | None = None,
                   max_probability: float | None = None,
                   min_interval_hours: float | None = None,
                   bayesian_threshold: float | None = None,
                   quiet_hours_start: str = "",
                   quiet_hours_end: str = "") -> dict:
    """Adjust the engagement engine configuration (global).

    Only non-empty / non-None values are updated. All probabilities are
    clamped to sane ranges. Returns the resulting config.

    Args:
        lambda_rate: Base longing rate (events/hour), >0.
        check_interval_minutes: Dice roll frequency in minutes, >0.
        growth_factor: How fast longing grows per miss/hold, 0-1.
        max_probability: Longing cap, 0-1.
        min_interval_hours: Anti-spam cooldown in hours, >0.
        bayesian_threshold: Send utility threshold, 0-1.
        quiet_hours_start: Quiet window start "HH:MM", e.g. "00:00".
        quiet_hours_end: Quiet window end "HH:MM", e.g. "08:00".
    """
    cfg = _load_config()
    with _lock:
        if lambda_rate is not None and lambda_rate > 0:
            cfg["lambda_rate"] = float(lambda_rate)
        if check_interval_minutes is not None and check_interval_minutes > 0:
            cfg["check_interval_minutes"] = int(check_interval_minutes)
        if growth_factor is not None:
            cfg["growth_factor"] = max(0.0, min(1.0, float(growth_factor)))
        if max_probability is not None:
            cfg["max_probability"] = max(0.0, min(1.0, float(max_probability)))
        if min_interval_hours is not None and min_interval_hours > 0:
            cfg["min_interval_hours"] = float(min_interval_hours)
        if bayesian_threshold is not None:
            cfg["bayesian_threshold"] = max(0.0, min(1.0, float(bayesian_threshold)))
        if quiet_hours_start:
            cfg["quiet_hours_start"] = quiet_hours_start
        if quiet_hours_end:
            cfg["quiet_hours_end"] = quiet_hours_end
        _save_config(cfg)
    return cfg


@mcp.tool()
def love_list_users() -> list[str]:
    """List user IDs that have an engagement state (for the scheduler)."""
    if not REVIVE_DIR.is_dir():
        return []
    return sorted(p.stem for p in REVIVE_DIR.glob("*.json"))


@mcp.tool()
def storage_info(user_id: str) -> dict:
    """Declare where this plugin stores data for the given user (internal use).

    Returns the concrete file paths that belong to `user_id`, so the bot can
    delete them when clearing the user's data. Plugins without this tool are
    treated as "compatibility mode": their data cannot be removed.
    """
    return {
        "user_data": [
            {"kind": "file", "path": str(_user_file(user_id))},
        ]
    }


@mcp.resource("revive://stats/{user_id}")
def revive_stats(user_id: str) -> str:
    """Engagement stats for a user: current longing probability and state."""
    uid = _sanitize_user_id(user_id)
    cfg = _load_config()
    with _lock:
        state = _load_state(uid) or _new_state(cfg)
        estimator = StateEstimator(state["belief"], state.get("learned"))
        best, _ = estimator.most_likely()
    return (
        f"渴望度 {state['probability']:.0%}，推断状态 {STATE_ZH.get(best, best)}，"
        f"未回复 {state.get('my_unanswered', 0)} 条"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
