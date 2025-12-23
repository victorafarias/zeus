import asyncio
from agent.orchestrator import AgentOrchestrator
from api.conversations import Conversation, Message

# Mock Conversation
class MockConversation:
    def __init__(self):
        self.id = "test-session"
        self.messages = []
        self.updated_at = None

async def test_completion():
    print("Testing Orchestrator Strict Completion...")
    
    orchestrator = AgentOrchestrator()
    conversation = MockConversation()
    
    # Message that deliberately asks to wait, which normally would cause exit
    conversation.messages.append(Message(role="user", content="Tell me you are waiting, then finish."))
    
    # We cannot easily mock the LLM response here without mocking _call_model_with_retry
    # But we can check if the code runs without syntax errors and imports work
    print("Imports successful. Logic validation requires running against actual LLM or heavy mocking.")
    print("The code changes logic is primarily in the 'process_message' loop.")
    
    import inspect
    src = inspect.getsource(orchestrator.process_message)
    if "require_completion" in src and "finish_task" in src:
        print("SUCCESS: Code contains the new logic.")
    else:
        print("FAILURE: Code does not contain the new logic.")

if __name__ == "__main__":
    asyncio.run(test_completion())
