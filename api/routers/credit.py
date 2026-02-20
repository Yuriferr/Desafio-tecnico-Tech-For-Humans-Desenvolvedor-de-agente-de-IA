from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import os
import datetime
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from dotenv import load_dotenv

# Importar Sessão Compartilhada
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from sessao import obter_sessao, atualizar_sessao

# Configuração
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
router = APIRouter(prefix="/credito", tags=["Agente de Crédito"])

# Modelos
class EntradaChat(BaseModel):
    id_sessao: str
    mensagem: str

class SaidaChat(BaseModel):
    resposta: str
    acao: str = "continuar" 
    alvo: Optional[str] = None
    id_sessao: str

# Dados
PASTA_DADOS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ARQUIVO_SOLICITACOES = os.path.join(PASTA_DADOS, "solicitacoes_aumento_limite.csv")
ARQUIVO_SCORE_LIMITE = os.path.join(PASTA_DADOS, "score_limite.csv")

# LLM
def obter_llm():
    chave = os.getenv("GOOGLE_API_KEY")
    return ChatGoogleGenerativeAI(
        google_api_key=chave,
        model="gemini-3-flash-preview",
        temperature=0.0
    )

# Funções Auxiliares
def verificar_limite_score(score, novo_limite):
    try:
        df = pd.read_csv(ARQUIVO_SCORE_LIMITE)
        if df.empty: return False
        
        # Encontrar faixa de score
        # Assumindo score numérico
        score = int(score)
        faixa = df[(df['min_score'] <= score) & (df['max_score'] >= score)]
        
        if not faixa.empty:
            limite_max = float(faixa.iloc[0]['limite_maximo'])
            return novo_limite <= limite_max
        return False
    except Exception as e:
        print(f"Erro ao verificar score: {e}")
        return False

def registrar_solicitacao(dados):
    # cpf_cliente,data_hora_solicitacao,limite_atual,novo_limite_solicitado,status_pedido
    try:
        colunas = ["cpf_cliente", "data_hora_solicitacao", "limite_atual", "novo_limite_solicitado", "status_pedido"]
        if not os.path.exists(ARQUIVO_SOLICITACOES):
            pd.DataFrame(columns=colunas).to_csv(ARQUIVO_SOLICITACOES, index=False)
            
        df = pd.DataFrame([dados])
        df.to_csv(ARQUIVO_SOLICITACOES, mode='a', header=False, index=False)
        return True
    except Exception as e:
        print(f"Erro ao registrar solicitação: {e}")
        return False

@router.post("/", response_model=SaidaChat)
async def endpoint_credito(entrada: EntradaChat):
    id_sessao = entrada.id_sessao
    mensagem = entrada.mensagem.strip()
    
    sessao = obter_sessao(id_sessao)
    if not sessao or not sessao.get("dados_cliente"):
        return SaidaChat(
            resposta="Sessão não encontrada ou não autenticada. Por favor, inicie pelo atendimento inicial.",
            acao="encerrar",
            id_sessao=id_sessao
        )

    # Estado Interno do Agente de Crédito
    # Se já estivermos "dentro" de um fluxo de solicitação, continuamos
    sub_estado = sessao.get("sub_estado_credito", "MENU")
    
    cliente = sessao["dados_cliente"]
    cpf = cliente.get("cpf")
    nome = cliente.get("nome")
    limite_atual = float(cliente.get("limite_credito", 0))
    score_atual = int(cliente.get("score", 0))

    resposta_texto = ""
    acao = "continuar"
    alvo = None

    llm = obter_llm()

    if sub_estado == "MENU":
        # Classificar se é consulta ou aumento
        prompt = ChatPromptTemplate.from_template("""
            Você é um assistente de crédito. O cliente disse: "{input}"
            Classifique a intenção:
            - consultar_limite (saber quanto tem, ver limite)
            - aumentar_limite (pedir mais crédito, aumentar, novo valor)
            - outros (assuntos não relacionados a crédito)

            Responda APENAS com a categoria.
        """)
        chain = prompt | llm | StrOutputParser()
        intencao = chain.invoke({"input": mensagem}).strip().lower()

        if "consultar" in intencao:
            resposta_texto = f"Seu limite de crédito atual é de R$ {limite_atual:.2f}. Posso ajudar com algo mais?"
            # Mantém no MENU para novas perguntas ou encerramento pelo usuário
        
        elif "aumentar" in intencao:
            resposta_texto = "Qual o novo valor de limite que você deseja solicitar?"
            sessao["sub_estado_credito"] = "AGUARDANDO_VALOR"
        
        else:
             resposta_texto = "Posso ajudar com consulta de limite ou solicitação de aumento. O que deseja?"

    elif sub_estado == "AGUARDANDO_VALOR":
        # Extrair valor financeiro da mensagem
        # Usar LLM ou Regex simples
        import re
        numeros = re.findall(r"[\d\.,]+", mensagem)
        if numeros:
            # Tentar limpar e converter o primeiro número encontrado
            valor_str = numeros[0].replace(".", "").replace(",", ".") # Assumindo formato brasileiro 1.000,00 -> 1000.00
            # Se tiver muitas falhas de parse, usar biblioteca ou LLM é melhor. Vamos simplificar:
            try:
                # Se tiver apenas um ponto e for milhar errado, ou virgula decimal... 
                # Abordagem segura: extrair via LLM
                prompt_valor = ChatPromptTemplate.from_template("""
                    Extraia o valor financeiro (número float) da mensagem: "{input}".
                    Responda apenas o número (ex: 5000.00). Se não achar, responda 0.
                """)
                chain_valor = prompt_valor | llm | StrOutputParser()
                novo_limite = float(chain_valor.invoke({"input": mensagem}).strip())
                
                if novo_limite > 0:
                    # Processar Solicitação
                    aprovado = verificar_limite_score(score_atual, novo_limite)
                    status = "aprovado" if aprovado else "rejeitado"
                    
                    # Registrar
                    dados_solicitacao = {
                        "cpf_cliente": cpf,
                        "data_hora_solicitacao": datetime.datetime.now().isoformat(),
                        "limite_atual": limite_atual,
                        "novo_limite_solicitado": novo_limite,
                        "status_pedido": status
                    }
                    registrar_solicitacao(dados_solicitacao)
                    
                    sessao["sub_estado_credito"] = "MENU" # Resetar sub-estado

                    if aprovado:
                        resposta_texto = f"Parabéns! Sua solicitação foi APROVADA de acordo com seu score atual de {score_atual}. Seu novo limite é R$ {novo_limite:.2f}."
                        # Atualizar na sessão/banco (simulado na sessão apenas para consistencia visual)
                        cliente["limite_credito"] = novo_limite 
                        # Atualizar no CSV Clientes se necessário (não pedido explicitamente mas ideal)
                    else:
                        resposta_texto = ("Infelizmente, seu score atual não permite esse limite no momento. "
                                          "Gostaria de falar com nosso Agente de Entrevista para atualizar seus dados e tentar melhorar seu score? (Responda Sim ou Não)")
                        atualizar_sessao(id_sessao, "sub_estado_credito", "OFERECER_ENTREVISTA")
                        sessao["sub_estado_credito"] = "OFERECER_ENTREVISTA" # Atualizar referencia local
                else:
                    resposta_texto = "Não entendi o valor. Poderia digitar novamente (ex: 5000)?"
            except ValueError:
                 resposta_texto = "Valor inválido. Tente novamente."
        else:
            resposta_texto = "Por favor, informe o valor numérico desejado."

    elif sub_estado == "OFERECER_ENTREVISTA":
        # Verificar sim/não
        if any(x in mensagem.lower() for x in ["sim", "quero", "aceito", "ss", "ok"]):
            resposta_texto = "Certo! Transferindo para o Agente de Entrevista..."
            acao = "transferir"
            alvo = "AgenteEntrevista"
            sessao["sub_estado_credito"] = "MENU" # Limpa estado
        else:
            resposta_texto = "Entendido. Posso ajudar com mais alguma coisa em relação ao seu crédito?"
            sessao["sub_estado_credito"] = "MENU"

    return SaidaChat(
        resposta=resposta_texto,
        acao=acao,
        alvo=alvo,
        id_sessao=id_sessao
    )
