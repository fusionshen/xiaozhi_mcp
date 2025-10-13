from typing import Dict
import time
import asyncio

SESSION_EXPIRE_SECONDS = 30 * 60

conversation_state: Dict[str, dict] = {}

def get_state(user_id: str):
    now = time.time()
    if user_id not in conversation_state:
        conversation_state[user_id] = {
            "indicator": None,
            "date": None,
            "formula": None,
            "formula_candidates": None,   # 候选列表
            "awaiting_confirmation": False, # 是否等待用户确认 top1
            "last_active": now
        }
    else:
        conversation_state[user_id]["last_active"] = now
    return conversation_state[user_id]

def update_state(user_id: str, new_data: dict):
    state = get_state(user_id)
    for k, v in new_data.items():
        if v is not None:
            state[k] = v
    state["last_active"] = time.time()
    conversation_state[user_id] = state
    return state

async def cleanup_expired_sessions():
    while True:
        now = time.time()
        expired = [uid for uid, s in conversation_state.items() if now - s.get("last_active", 0) > SESSION_EXPIRE_SECONDS]
        for uid in expired:
            del conversation_state[uid]
        await asyncio.sleep(60)
