from typing import Dict, Optional, TypedDict
import time
import asyncio

SESSION_EXPIRE_SECONDS = 30 * 60  # 30分钟过期

class SlotState(TypedDict, total=False):
    indicator: Optional[str]
    formula: Optional[str]
    formula_candidates: Optional[list]
    awaiting_confirmation: bool
    timeString: Optional[str]
    timeType: Optional[str]

class SessionState(TypedDict, total=False):
    slots: SlotState
    last_active: float

conversation_state: Dict[str, SessionState] = {}
_state_lock = asyncio.Lock()

def now() -> float:
    return time.time()

async def get_state(user_id: str) -> SessionState:
    async with _state_lock:
        state = conversation_state.get(user_id)
        if not state:
            state = {
                "slots": {
                    "indicator": None,
                    "formula": None,
                    "formula_candidates": None,
                    "awaiting_confirmation": False,
                    "timeString": None,
                    "timeType": None
                },
                "last_active": now()
            }
            conversation_state[user_id] = state
        else:
            state["last_active"] = now()
        return state

async def update_state(user_id: str, new_data: dict) -> SessionState:
    async with _state_lock:
        state = conversation_state.get(user_id)
        if not state:
            state = {
                "slots": {
                    "indicator": None,
                    "formula": None,
                    "formula_candidates": None,
                    "awaiting_confirmation": False,
                    "timeString": None,
                    "timeType": None
                },
                "last_active": now()
            }
            conversation_state[user_id] = state

        for k, v in new_data.items():
            if v is not None:
                state[k] = v
        state["last_active"] = now()
        conversation_state[user_id] = state
        return state

async def cleanup_once():
    async with _state_lock:
        current = now()
        expired = [
            uid for uid, s in conversation_state.items()
            if current - s.get("last_active", 0) > SESSION_EXPIRE_SECONDS
        ]
        for uid in expired:
            del conversation_state[uid]
        return expired

async def cleanup_expired_sessions():
    while True:
        expired = await cleanup_once()
        if expired:
            print(f"[agent_state] 清理过期会话: {expired}")
        await asyncio.sleep(60)

def default_slots():
    return {
        "indicator": None,
        "formula": None,
        "formula_candidates": None,
        "awaiting_confirmation": False,
        "timeString": None,
        "timeType": None,
        "last_input": None,
        "intent": "new_query"
    }
