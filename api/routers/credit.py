from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import os
import datetime
from langchain_ollama import ChatOllama
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
    # O Ollama deve estar rodando localmente (padrão porta 11434)
    # Modelo sugerido: llama3.2 (leve e eficiente)
    return ChatOllama(
        model="llama3.2",
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
    
    # Adicionar mensagem do usuário ao histórico global
    if "historico" not in sessao: sessao["historico"] = []
    sessao["historico"].append({"role": "user", "content": mensagem})

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
        # Formatar Histórico Recente
        historico_recente = ""
        for msg in sessao.get("historico", [])[-6:]:
            papel = "Usuário" if msg['role'] == 'user' else "Agente"
            conteudo = msg.get('content', '')
            if conteudo:
                historico_recente += f"{papel}: {conteudo}\n"

        # Classificar se é consulta ou aumento
        prompt = ChatPromptTemplate.from_template("""
            Você é um classificador de intenções para um agente de crédito. Considere o histórico.
            
            Histórico Recente:
            ------
            {historico}
            ------

            O usuário disse: "{input}"
            
            Classifique em UMA das opções abaixo:
            - consultar_limite (ver saldo, quanto tenho, limite atual)
            - aumentar_limite (pedir mais, aumentar, novo limite, solicitação de aumento)
            - encerrar (sair, tchau, obrigado, fim, cancelar)
            - outros

            Regra: Responda APENAS com o nome da categoria exata. Sem frases.
            Exemplo: aumentar_limite
            Resposta:
        """)
        chain = prompt | llm | StrOutputParser()
        intencao = chain.invoke({"input": mensagem, "historico": historico_recente}).strip().lower()

        # Limpeza para modelos locais
        if "aumentar" in intencao or "solicita" in intencao: intencao = "aumentar_limite"
        elif "consultar" in intencao or "ver" in intencao or "saldo" in intencao: intencao = "consultar_limite"
        elif "encerrar" in intencao or "sair" in intencao or "tchau" in intencao: intencao = "encerrar"
        
        # Detectar saída (mantido como fallback se a IA falhar muito, mas reduzido)
        if intencao not in ["aumentar_limite", "consultar_limite", "encerrar"]:
             if any(x in mensagem.lower() for x in ["não", "nao", "obrigado", "sair", "encerrar", "tchau", "nada"]):
                  intencao = "encerrar"
        
        print(f"DEBUG CRÉDITO: Mensagem '{mensagem}' classificada como '{intencao}'")

        if "consultar" in intencao:
            resposta_texto = f"Seu limite de crédito atual é de R$ {limite_atual:.2f}. Posso ajudar com algo mais?"
            # Mantém no MENU para novas perguntas ou encerramento pelo usuário
        
        elif "aumentar" in intencao:
            resposta_texto = "Qual o novo valor de limite que você deseja solicitar?"
            sessao["sub_estado_credito"] = "AGUARDANDO_VALOR"
        
        elif intencao == "encerrar":
            resposta_texto = "Entendido. Caso precise de mais alguma coisa, estamos à disposição. Até logo!"
            acao = "encerrar"

        else:
             resposta_texto = "Posso ajudar com consulta de limite ou solicitação de aumento. O que deseja?"


    elif sub_estado == "AGUARDANDO_VALOR":
        # Verificar cancelamento antes de processar valor
        if any(x in mensagem.lower() for x in ["cancelar", "sair", "voltar", "não", "nao", "desisti"]):
            resposta_texto = "Operação de aumento de limite cancelada. Posso ajudar com mais alguma coisa?"
            sessao["sub_estado_credito"] = "MENU"
            return SaidaChat(resposta=resposta_texto, acao="continuar", id_sessao=id_sessao)

        import re as regex_module
        # Procura por números no formato 0000 ou 0000.00 ou 0.000,00
        numeros = regex_module.findall(r"[\d\.,]+", mensagem)
        novo_limite = 0

        if numeros:
            for num_str in numeros:
                 # Tentativa de normalizar formato BR (1.000,00) para Float
                 clean_str = num_str
                 if ',' in clean_str and '.' in clean_str:
                     clean_str = clean_str.replace('.', '').replace(',', '.')
                 elif ',' in clean_str:
                     clean_str = clean_str.replace(',', '.')
                 
                 try:
                     val = float(clean_str)
                     if val > 0:
                         novo_limite = val
                         break
                 except:
                     continue
        
        if novo_limite > 0:
            # Processar Solicitação OK
            aprovado = verificar_limite_score(score_atual, novo_limite)
            status = "aprovado" if aprovado else "rejeitado"
            
            dados_solicitacao = {
                "cpf_cliente": cpf,
                "data_hora_solicitacao": datetime.datetime.now().isoformat(),
                "limite_atual": limite_atual,
                "novo_limite_solicitado": novo_limite,
                "status_pedido": status
            }
            registrar_solicitacao(dados_solicitacao)
            
            sessao["sub_estado_credito"] = "MENU"

            if aprovado:
                resposta_texto = f"Parabéns! Sua solicitação foi APROVADA de acordo com seu score atual de {score_atual}. Seu novo limite é R$ {novo_limite:.2f}."
                cliente["limite_credito"] = novo_limite 
            else:
                resposta_texto = ("Infelizmente, seu score atual não permite esse limite no momento. "
                                  "Quer fazer uma entrevista para atualizar seus dados e conferir se pode aumentar seu score? (Responda Sim ou Não)")
                atualizar_sessao(id_sessao, "sub_estado_credito", "OFERECER_ENTREVISTA")
                sessao["sub_estado_credito"] = "OFERECER_ENTREVISTA"
        else:
             resposta_texto = "Não consegui entender o valor. Por favor, digite apenas o número (ex: 5000)."

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
