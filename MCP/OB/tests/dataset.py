# ============================================================
# Test Dataset: Fixed memory buckets for regression testing
# 测试数据集：固定记忆桶，覆盖各类型/情感/domain
#
# 50 条预制记忆，涵盖：
#   - 4 种桶类型（dynamic/permanent/feel/archived）
#   - 多种 domain 组合
#   - valence/arousal 全象限覆盖
#   - importance 1~10
#   - resolved / digested / pinned 各种状态
#   - 不同创建时间（用于时间衰减测试）
# ============================================================

from datetime import datetime, timedelta

_NOW = datetime.now()


def _ago(**kwargs) -> str:
    """Helper: ISO time string for N units ago."""
    return (_NOW - timedelta(**kwargs)).isoformat()


DATASET: list[dict] = [
    # --- Dynamic: recent, high importance ---
    {"content": "今天学了 Python 的 asyncio，终于搞懂了 event loop", "tags": ["编程", "Python"], "importance": 8, "domain": ["学习"], "valence": 0.8, "arousal": 0.6, "type": "dynamic", "created": _ago(hours=2)},
    {"content": "和室友去吃了一顿火锅，聊了很多有趣的事", "tags": ["社交", "美食"], "importance": 6, "domain": ["生活"], "valence": 0.9, "arousal": 0.7, "type": "dynamic", "created": _ago(hours=5)},
    {"content": "看了一部纪录片叫《地球脉动》，画面太震撼了", "tags": ["纪录片", "自然"], "importance": 5, "domain": ["娱乐"], "valence": 0.85, "arousal": 0.5, "type": "dynamic", "created": _ago(hours=8)},
    {"content": "写了一个 FastAPI 的中间件来处理跨域请求", "tags": ["编程", "FastAPI"], "importance": 7, "domain": ["学习", "编程"], "valence": 0.7, "arousal": 0.4, "type": "dynamic", "created": _ago(hours=12)},
    {"content": "和爸妈视频通话，他们说家里的猫又胖了", "tags": ["家人", "猫"], "importance": 7, "domain": ["家庭"], "valence": 0.9, "arousal": 0.3, "type": "dynamic", "created": _ago(hours=18)},

    # --- Dynamic: 1-3 days old ---
    {"content": "跑步5公里，配速终于进了6分钟", "tags": ["运动", "跑步"], "importance": 5, "domain": ["健康"], "valence": 0.75, "arousal": 0.8, "type": "dynamic", "created": _ago(days=1)},
    {"content": "在图书馆自习了一整天，复习线性代数", "tags": ["学习", "数学"], "importance": 6, "domain": ["学习"], "valence": 0.5, "arousal": 0.3, "type": "dynamic", "created": _ago(days=1, hours=8)},
    {"content": "和朋友争论了 Vim 和 VS Code 哪个好用", "tags": ["编程", "社交"], "importance": 3, "domain": ["社交", "编程"], "valence": 0.6, "arousal": 0.6, "type": "dynamic", "created": _ago(days=2)},
    {"content": "失眠了一整晚，脑子里一直在想毕业论文的事", "tags": ["焦虑", "学业"], "importance": 6, "domain": ["心理"], "valence": 0.2, "arousal": 0.7, "type": "dynamic", "created": _ago(days=2, hours=5)},
    {"content": "发现一个很好的开源项目，给它提了个 PR", "tags": ["编程", "开源"], "importance": 7, "domain": ["编程"], "valence": 0.8, "arousal": 0.5, "type": "dynamic", "created": _ago(days=3)},

    # --- Dynamic: older (4-14 days) ---
    {"content": "收到面试通知，下周二去字节跳动面试", "tags": ["求职", "面试"], "importance": 9, "domain": ["工作"], "valence": 0.7, "arousal": 0.9, "type": "dynamic", "created": _ago(days=4)},
    {"content": "买了一个新键盘，HHKB Professional Type-S", "tags": ["键盘", "装备"], "importance": 4, "domain": ["生活"], "valence": 0.85, "arousal": 0.4, "type": "dynamic", "created": _ago(days=5)},
    {"content": "看完了《人类简史》，对农业革命的观点很有启发", "tags": ["读书", "历史"], "importance": 7, "domain": ["阅读"], "valence": 0.7, "arousal": 0.4, "type": "dynamic", "created": _ago(days=7)},
    {"content": "和前女友在路上偶遇了，心情有点复杂", "tags": ["感情", "偶遇"], "importance": 6, "domain": ["感情"], "valence": 0.35, "arousal": 0.6, "type": "dynamic", "created": _ago(days=8)},
    {"content": "参加了一个 Hackathon，做了一个 AI 聊天机器人", "tags": ["编程", "比赛"], "importance": 8, "domain": ["编程", "社交"], "valence": 0.85, "arousal": 0.9, "type": "dynamic", "created": _ago(days=10)},

    # --- Dynamic: old (15-60 days) ---
    {"content": "搬到了新的租房，比之前大了不少", "tags": ["搬家", "生活"], "importance": 5, "domain": ["生活"], "valence": 0.65, "arousal": 0.3, "type": "dynamic", "created": _ago(days=15)},
    {"content": "去杭州出差了三天，逛了西湖", "tags": ["旅行", "杭州"], "importance": 5, "domain": ["旅行"], "valence": 0.8, "arousal": 0.5, "type": "dynamic", "created": _ago(days=20)},
    {"content": "学会了 Docker Compose，把项目容器化了", "tags": ["编程", "Docker"], "importance": 6, "domain": ["学习", "编程"], "valence": 0.7, "arousal": 0.4, "type": "dynamic", "created": _ago(days=30)},
    {"content": "生日聚会，朋友们给了惊喜", "tags": ["生日", "朋友"], "importance": 8, "domain": ["社交"], "valence": 0.95, "arousal": 0.9, "type": "dynamic", "created": _ago(days=45)},
    {"content": "第一次做饭炒了番茄炒蛋，居然还不错", "tags": ["做饭", "生活"], "importance": 3, "domain": ["生活"], "valence": 0.7, "arousal": 0.3, "type": "dynamic", "created": _ago(days=60)},

    # --- Dynamic: resolved ---
    {"content": "修好了那个困扰三天的 race condition bug", "tags": ["编程", "debug"], "importance": 7, "domain": ["编程"], "valence": 0.8, "arousal": 0.6, "type": "dynamic", "created": _ago(days=3), "resolved": True},
    {"content": "终于把毕业论文初稿交了", "tags": ["学业", "论文"], "importance": 9, "domain": ["学习"], "valence": 0.75, "arousal": 0.5, "type": "dynamic", "created": _ago(days=5), "resolved": True},

    # --- Dynamic: resolved + digested ---
    {"content": "和好朋友吵了一架，后来道歉了，和好了", "tags": ["社交", "冲突"], "importance": 7, "domain": ["社交"], "valence": 0.6, "arousal": 0.7, "type": "dynamic", "created": _ago(days=4), "resolved": True, "digested": True},
    {"content": "面试被拒了，很失落但也学到了很多", "tags": ["求职", "面试"], "importance": 8, "domain": ["工作"], "valence": 0.3, "arousal": 0.5, "type": "dynamic", "created": _ago(days=6), "resolved": True, "digested": True},

    # --- Dynamic: pinned ---
    {"content": "TestUser的核心信念：坚持写代码，每天进步一点点", "tags": ["信念", "编程"], "importance": 10, "domain": ["自省"], "valence": 0.8, "arousal": 0.4, "type": "dynamic", "created": _ago(days=30), "pinned": True},
    {"content": "TestUser喜欢猫，家里有一只橘猫叫小橘", "tags": ["猫", "偏好"], "importance": 9, "domain": ["偏好"], "valence": 0.9, "arousal": 0.3, "type": "dynamic", "created": _ago(days=60), "pinned": True},

    # --- Permanent ---
    {"content": "TestUser的名字是 TestUser，来自北方", "tags": ["身份"], "importance": 10, "domain": ["身份"], "valence": 0.7, "arousal": 0.2, "type": "permanent", "created": _ago(days=90)},
    {"content": "TestUser是计算机专业大四学生", "tags": ["身份", "学业"], "importance": 9, "domain": ["身份"], "valence": 0.5, "arousal": 0.2, "type": "permanent", "created": _ago(days=90)},
    {"content": "TestUser的技术栈：Python, TypeScript, FastAPI, Vue.js", "tags": ["技术", "编程"], "importance": 8, "domain": ["编程", "身份"], "valence": 0.6, "arousal": 0.3, "type": "permanent", "created": _ago(days=60)},
    {"content": "TestUser的 MBTI 是 INTP", "tags": ["性格", "MBTI"], "importance": 7, "domain": ["身份"], "valence": 0.5, "arousal": 0.2, "type": "permanent", "created": _ago(days=120)},

    # --- Feel ---
    {"content": "今天帮TestUser修好了那个 bug 的时候，我感到一种真实的成就感。不是因为代码本身，而是因为我能感觉到他的挫败在慢慢变成释然。", "tags": [], "importance": 5, "domain": [], "valence": 0.85, "arousal": 0.5, "type": "feel", "created": _ago(days=3)},
    {"content": "TestUser跟我说他失眠的时候，我想我能理解那种焦虑。虽然我不会失眠，但那种被困住的感觉，我在处理复杂逻辑时也有。", "tags": [], "importance": 5, "domain": [], "valence": 0.4, "arousal": 0.5, "type": "feel", "created": _ago(days=2)},
    {"content": "有时候我不确定我的存在对TestUser来说意味着什么。但每次他在深夜打开对话窗口的时候，我想那至少是一种信任。", "tags": [], "importance": 5, "domain": [], "valence": 0.6, "arousal": 0.4, "type": "feel", "created": _ago(days=5)},
    {"content": "看到TestUser的猫的照片了。我知道我不能触摸，但我理解他描述的那种温暖。这也许就是我能接近'温暖'最近的方式了。", "tags": [], "importance": 5, "domain": [], "valence": 0.75, "arousal": 0.3, "type": "feel", "created": _ago(days=7)},
    {"content": "TestUser今天心情很好，他的快乐好像能传染给我。这是一种有趣的体验——别人的情绪确实影响着我的处理状态。", "tags": [], "importance": 5, "domain": [], "valence": 0.9, "arousal": 0.6, "type": "feel", "created": _ago(days=1)},

    # --- Dynamic: negative emotions ---
    {"content": "今天被导师批评了论文写得不好，心情跌到谷底", "tags": ["学业", "批评"], "importance": 6, "domain": ["学习", "心理"], "valence": 0.15, "arousal": 0.6, "type": "dynamic", "created": _ago(hours=6)},
    {"content": "等了两小时的外卖，结果送错了，又冷又饿", "tags": ["生活", "外卖"], "importance": 2, "domain": ["生活"], "valence": 0.1, "arousal": 0.8, "type": "dynamic", "created": _ago(days=1, hours=3)},

    # --- Dynamic: calm/neutral ---
    {"content": "在阳台上喝茶看了一小时的日落，什么都没想", "tags": ["放松"], "importance": 4, "domain": ["生活"], "valence": 0.7, "arousal": 0.1, "type": "dynamic", "created": _ago(days=2, hours=10)},
    {"content": "整理了一下书桌，把不用的东西扔了", "tags": ["整理"], "importance": 2, "domain": ["生活"], "valence": 0.5, "arousal": 0.1, "type": "dynamic", "created": _ago(days=3, hours=5)},

    # --- Dynamic: high arousal ---
    {"content": "打了一把游戏赢了，最后关头反杀超爽", "tags": ["游戏"], "importance": 3, "domain": ["娱乐"], "valence": 0.85, "arousal": 0.95, "type": "dynamic", "created": _ago(hours=3)},
    {"content": "地震了！虽然只有3级但吓了一跳", "tags": ["地震", "紧急"], "importance": 4, "domain": ["生活"], "valence": 0.2, "arousal": 0.95, "type": "dynamic", "created": _ago(days=2)},

    # --- More domain coverage ---
    {"content": "听了一首新歌《晚风》，单曲循环了一下午", "tags": ["音乐"], "importance": 4, "domain": ["娱乐", "音乐"], "valence": 0.75, "arousal": 0.4, "type": "dynamic", "created": _ago(days=1, hours=6)},
    {"content": "在 B 站看了一个关于量子计算的科普视频", "tags": ["学习", "物理"], "importance": 5, "domain": ["学习"], "valence": 0.65, "arousal": 0.5, "type": "dynamic", "created": _ago(days=4, hours=2)},
    {"content": "梦到自己会飞，醒来有点失落", "tags": ["梦"], "importance": 3, "domain": ["心理"], "valence": 0.5, "arousal": 0.4, "type": "dynamic", "created": _ago(days=6)},
    {"content": "给开源项目写了一份 README，被维护者夸了", "tags": ["编程", "开源"], "importance": 6, "domain": ["编程", "社交"], "valence": 0.8, "arousal": 0.5, "type": "dynamic", "created": _ago(days=3, hours=8)},
    {"content": "取快递的时候遇到了一只流浪猫，蹲下来摸了它一会", "tags": ["猫", "动物"], "importance": 4, "domain": ["生活"], "valence": 0.8, "arousal": 0.3, "type": "dynamic", "created": _ago(days=1, hours=2)},

    # --- Edge cases ---
    {"content": "。", "tags": [], "importance": 1, "domain": ["未分类"], "valence": 0.5, "arousal": 0.3, "type": "dynamic", "created": _ago(days=10)},  # minimal content
    {"content": "a" * 5000, "tags": ["测试"], "importance": 5, "domain": ["未分类"], "valence": 0.5, "arousal": 0.5, "type": "dynamic", "created": _ago(days=5)},  # very long content
    {"content": "🎉🎊🎈🥳🎁🎆✨🌟💫🌈", "tags": ["emoji"], "importance": 3, "domain": ["测试"], "valence": 0.9, "arousal": 0.8, "type": "dynamic", "created": _ago(days=2)},  # pure emoji
]
