import asyncio
import os
import sys

# Adicionar diretório atual ao path para importar modules
sys.path.append(os.getcwd())

from agent.tools.tts_tool import TextToSpeechTool

async def test():
    print("Iniciando teste de TTS...")
    tool = TextToSpeechTool()
    
    # Teste básico
    result = await tool.execute(
        text="Olá, este é um teste do sistema de voz do Zeus. Estamos operando em modo de teste.",
        language="pt"
    )
    
    print("\nResultado:")
    print(result)

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test())
