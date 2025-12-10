# app/domains/energy/utils.py
import config

def normalize_symbol_in_string(s: str) -> str:
    """
    根据 ENABLE_REMOVE_SYMBOLS 动态清洗示例字符串：
    - 删除第一次出现的 '#' 或 '号'（按最左位置）
    """
    if not config.ENABLE_REMOVE_SYMBOLS:
        return s

    # 找两个符号的位置
    pos_hash = s.find("#")
    pos_hao = s.find("号")

    # 都不存在
    if pos_hash == -1 and pos_hao == -1:
        return s

    # 只存在一种符号
    if pos_hash == -1:
        return s[:pos_hao] + s[pos_hao+1:]
    if pos_hao == -1:
        return s[:pos_hash] + s[pos_hash+1:]

    # 两者都存在 → 删最左边的
    if pos_hash < pos_hao:
        return s[:pos_hash] + s[pos_hash+1:]
    else:
        return s[:pos_hao] + s[pos_hao+1:]