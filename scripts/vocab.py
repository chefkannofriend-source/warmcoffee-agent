"""
口感词汇映射 — 个人词典

CLI 用法：
  python3 scripts/vocab.py check "红糖,厚重,明亮"   # 检查哪些词未知
  python3 scripts/vocab.py update "红糖" 1           # 写入词典（1=苦/厚，-1=酸/亮，0=平衡）
"""

import json
import os
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
VOCAB_DIR = os.path.join(DATA_DIR, "vocab")
DEFAULT_VOCAB_PATH = os.path.join(VOCAB_DIR, "personal.json")

# 内置种子词典（仅作初始化用，不共用）
SEED_VOCAB = {
    "sharp": -1,
    "bright": -1,
    "sour": -1,
    "acidic": -1,
    "harsh": 1,
    "bitter": 1,
    "astringent": 1,
    "clean": 0,
    "balanced": 0,
    "off today": "WARM_flag",
    "not feeling well": "WARM_flag",
    "sick": "WARM_flag",
    "tired": "WARM_flag",
}


def load_vocab(user_id: str = "personal") -> dict:
    """读取用户词典，不存在则用种子初始化"""
    path = os.path.join(VOCAB_DIR, f"{user_id}.json")
    if not os.path.exists(path):
        _init_vocab(path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _init_vocab(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(SEED_VOCAB, f, ensure_ascii=False, indent=2)


def normalize_word(word: str) -> str:
    """
    去掉程度副词和语气词，提取核心味觉词。
    「挺干净的」→「干净」  /  「very bright」→「bright」
    """
    import re
    w = word.strip()

    # 中文：去头部程度副词
    zh_prefixes = r'^(挺|蛮|很|非常|比较|有点|有些|略|稍|还|真|太|相当|颇|特别|十分|超|好|超级)+'
    w = re.sub(zh_prefixes, '', w)
    # 中文：去尾部语气词
    zh_suffixes = r'(的|了|啊|呢|哦|嘛|吧)+$'
    w = re.sub(zh_suffixes, '', w)

    # 英文：去头部修饰词
    en_prefixes = r'^(very|quite|pretty|rather|a bit|a little|slightly|somewhat|super|really|too)\s+'
    w = re.sub(en_prefixes, '', w, flags=re.IGNORECASE)

    return w.strip() or word.strip()  # 万一全被剥掉，回退原词


def map_taste_word(word: str, vocab: dict):
    """
    返回：
      -1  → 偏酸/偏尖（调粗方向）
       0  → 平衡
      +1  → 偏苦/偏涩（调细方向）
      "WARM_flag" → 触发 WARM
      None → 未知词，需询问用户
    先查原词，再查规范化后的词。
    """
    w = word.strip()
    if w in vocab:
        return vocab[w]
    normalized = normalize_word(w)
    return vocab.get(normalized, None)


def update_vocab(word: str, value, user_id: str = "personal") -> None:
    """用户确认后写入词典（存规范化后的核心词）"""
    path = os.path.join(VOCAB_DIR, f"{user_id}.json")
    vocab = load_vocab(user_id)
    normalized = normalize_word(word.strip())
    vocab[normalized] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)
    if _is_cjk(word):
        print(f"✓ 词典已更新：「{word}」→ {value}")
    else:
        print(f"✓ Vocab updated: \"{word}\" → {value}")


def parse_taste_input(raw_input: str, vocab: dict) -> dict:
    """
    解析用户的口感描述，返回：
    {
        "score": float | None,    # 加权平均，None = 无有效数据
        "warm_flag": bool,
        "unknown_words": [str],
        "words_used": [(word, value)]
    }
    """
    words = [w.strip() for w in raw_input.replace("，", ",").replace("、", ",").split(",") if w.strip()]
    if not words:
        # 尝试按空格切分
        words = raw_input.strip().split()

    scores = []
    warm_flag = False
    unknown_words = []
    words_used = []

    for word in words:
        val = map_taste_word(word, vocab)
        if val is None:
            unknown_words.append(word)
        elif val == "WARM_flag":
            warm_flag = True
            words_used.append((word, "WARM_flag"))
        else:
            scores.append(val)
            words_used.append((word, val))

    avg_score = round(sum(scores) / len(scores), 2) if scores else None

    return {
        "score": avg_score,
        "warm_flag": warm_flag,
        "unknown_words": unknown_words,
        "words_used": words_used,
    }


def _is_cjk(text: str) -> bool:
    """Return True if the text contains CJK (Chinese/Japanese/Korean) characters."""
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def prompt_for_unknown(word: str) -> str:
    """Ask user to clarify an unknown taste word, in the same language as the word."""
    if _is_cjk(word):
        return f"你说的「{word}」，是偏酸/偏亮，还是偏苦/偏涩？（输入：酸 / 苦 / 平衡 / warm）"
    return f"When you say \"{word}\" — sour/bright or bitter/harsh? (sour / bitter / balanced / warm)"


def check_taste(raw_input: str, user_id: str = "personal") -> None:
    """
    CLI helper: parse taste input and report unknown words BEFORE session log.
    Agent calls this first; resolves unknowns via update_vocab; then calls session.py log.

    Output format (one line per token):
      OK: word → value
      UNKNOWN: word
      WARM_FLAG: word
    """
    vocab = load_vocab(user_id)
    words = [w.strip() for w in raw_input.replace("，", ",").replace("、", ",").split(",") if w.strip()]
    if not words:
        words = raw_input.strip().split()

    for word in words:
        val = map_taste_word(word, vocab)
        if val is None:
            print(f"UNKNOWN: {word}")
        elif val == "WARM_flag":
            print(f"WARM_FLAG: {word}")
        else:
            print(f"OK: {word} → {val}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="个人词典工具")
    sub = parser.add_subparsers(dest="cmd")

    c = sub.add_parser("check", help="检查味觉词汇是否已知")
    c.add_argument("words", help="逗号分隔的味觉描述，如 '红糖,明亮,厚重'")

    u = sub.add_parser("update", help="写入新词汇")
    u.add_argument("word")
    u.add_argument("value", help="1=苦/厚  -1=酸/亮  0=平衡  warm=WARM标记")

    args = parser.parse_args()

    if args.cmd == "check":
        check_taste(args.words)
    elif args.cmd == "update":
        val = args.value
        if val not in ("warm",):
            try:
                val = float(val)
                if val == int(val):
                    val = int(val)
            except ValueError:
                print(f"错误：value 必须是数字或 'warm'，收到 '{args.value}'")
                sys.exit(1)
        update_vocab(args.word, val)
    else:
        parser.print_help()
