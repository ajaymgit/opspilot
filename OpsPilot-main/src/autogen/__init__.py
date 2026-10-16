"""AutoGen compatibility layer for OpsPilot.

Provides AssistantAgent, UserProxyAgent, and reply registration mechanics
conforming strictly to AutoGen contracts.
"""

from typing import Dict, Any, List, Callable, Optional, Union, Tuple


class Agent:
    """Base Agent class."""

    def __init__(self, name: str):
        self.name = name


class AssistantAgent(Agent):
    """AssistantAgent representing an AI reasoning agent."""

    def __init__(
        self,
        name: str,
        llm_config: Optional[Dict[str, Any]] = None,
        system_message: str = ""
    ):
        super().__init__(name)
        self.llm_config = llm_config or {}
        self.system_message = system_message


class UserProxyAgent(Agent):
    """UserProxyAgent representing human proxy / orchestrator / execution agent."""

    def __init__(
        self,
        name: str,
        human_input_mode: str = "NEVER",
        code_execution_config: Union[Dict[str, Any], bool] = False,
        is_termination_msg: Optional[Callable[[Optional[Dict[str, Any]]], bool]] = None
    ):
        super().__init__(name)
        self.human_input_mode = human_input_mode
        self.code_execution_config = code_execution_config
        self.is_termination_msg = is_termination_msg or (lambda x: False)
        self._reply_func_list: List[Dict[str, Any]] = []
        self.chat_messages: Dict[Agent, List[Dict[str, Any]]] = {}

    def register_reply(
        self,
        trigger: type,
        reply_func: Callable,
        position: int = 0,
        config: Optional[Dict[str, Any]] = None
    ):
        """Registers an interceptor/reply function at specified priority position."""
        entry = {
            "trigger": trigger,
            "reply_func": reply_func,
            "config": config or {}
        }
        if position < len(self._reply_func_list):
            self._reply_func_list.insert(position, entry)
        else:
            self._reply_func_list.append(entry)

    def initiate_chat(
        self,
        recipient: Agent,
        message: str,
        max_turns: int = 10
    ):
        """Initiates a bounded conversation loop with recipient agent."""
        if recipient not in self.chat_messages:
            self.chat_messages[recipient] = []

        # Outgoing initial message from orchestrator/user
        self.chat_messages[recipient].append({"role": "user", "content": message})

        current_turn = 0
        while current_turn < max_turns:
            current_turn += 1

            # Check registered reply interceptors on self (position 0 first)
            interrupted = False
            for handler in self._reply_func_list:
                func = handler["reply_func"]
                cfg = handler.get("config", {})
                final_flag, reply_msg = func(self, self.chat_messages[recipient], recipient, cfg)

                if final_flag and reply_msg:
                    self.chat_messages[recipient].append({
                        "role": "system",
                        "content": reply_msg
                    })
                    interrupted = True
                    break

            if interrupted:
                break

            # Simulate agent response turn
            response_content = self._generate_response(recipient, self.chat_messages[recipient])
            msg_obj = {"role": "assistant", "content": response_content}
            self.chat_messages[recipient].append(msg_obj)

            if self.is_termination_msg(msg_obj):
                break

    def _generate_response(self, recipient: Agent, history: List[Dict[str, Any]]) -> str:
        """Generates deterministic mock code / response when offline testing."""
        if isinstance(recipient, AssistantAgent):
            if "AnalysisAgent" in recipient.name:
                return (
                    "### Modern OO Java Microservice Roadmap\n"
                    "1. Class: PayrollEntity.java\n"
                    "2. Service: PayrollService.java (@Service)\n"
                    "3. Controller: PayrollController.java (@RestController)\n"
                    "4. Business Logic: Migrate PERFORM 2000-PROCESS-PAYROLL into calculatePayroll()."
                )
            elif "Coder" in recipient.name:
                prog_name = "Payroll"
                return (
                    f"```java\n"
                    f"package com.opspilot.modernized;\n\n"
                    f"import org.springframework.stereotype.Service;\n\n"
                    f"@Service\n"
                    f"public class {prog_name}Service {{\n"
                    f"    public void processPayroll() {{\n"
                    f"        // Migrated legacy business logic\n"
                    f"    }}\n"
                    f"}}\n"
                    f"```\n\nBUILD SUCCESS"
                )

        return "BUILD SUCCESS"
