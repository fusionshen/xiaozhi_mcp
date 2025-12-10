# app/domains/energy/domain.py
from . import llm
from . import ask
from . import api


class EnergyDomain:
    """
    统一能源领域入口，让所有功能都从 domain.energy 访问。
    用法：
        energy = EnergyDomain()
        energy.llm.parse_user_input(...)
        energy.pipeline.process_message(...)
        energy.api.FormulaAPI(...)
    """
    
    def __init__(self):
        self.llm = llm
        self.ask = ask
        self.api = api


__all__ = ["EnergyDomain"]
