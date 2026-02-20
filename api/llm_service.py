from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser

def obter_llm():
    return ChatOllama(
        model="llama3.2",
        temperature=0.0
    )

def formatar_historico(historico):
    historico_str = ""
    if not historico:
        return ""
    for msg in historico[-6:]:
        papel = "Usuário" if msg['role'] == 'user' else "Agente"
        conteudo = msg.get('content', '')
        if conteudo:
            historico_str += f"{papel}: {conteudo}\n"
    return historico_str

def consultar_llm(mensagem, historico, instrucao, formato="texto"):
    """
    Função global para consultar a Llama, passando a instrução e o histórico.
    `formato` pode ser 'texto' (retorna string) ou 'json' (retorna um dicionário).
    """
    llm = obter_llm()
    historico_str = formatar_historico(historico)
    
    template = """
{instrucao}

IMPORTANTE: 
1. Se a mensagem atual revelar explicitamente a intenção do usuário de sair, encerrar, parar o atendimento, ou dizer que não quer mais falar com o banco, você DEVE retornar a intenção de 'encerrar'.
2. Se a mensagem atual revelar explicitamente a intenção do usuário de voltar ao menu principal, ver as opções novamente, trocar de assunto, ou falar com a triagem, você DEVE retornar a intenção de 'voltar'.

Histórico recente:
---
{historico}
---

Mensagem do Usuário: "{mensagem}"

Sua Resposta:
    """
    
    prompt = ChatPromptTemplate.from_template(template)
    
    if formato == "json":
        parser = JsonOutputParser()
        chain = prompt | llm | parser
        try:
            return chain.invoke({"instrucao": instrucao, "historico": historico_str, "mensagem": mensagem})
        except Exception as e:
            print(f"Falha de parse JSON LLM: {e}")
            return {"erro_llm": True}
    else:
        chain = prompt | llm | StrOutputParser()
        try:
            return chain.invoke({"instrucao": instrucao, "historico": historico_str, "mensagem": mensagem}).strip().lower()
        except Exception as e:
            print(f"Erro de conexão com LLM: {e}")
            return "erro_llm"

