from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import os
import datetime
from dotenv import load_dotenv

# Importar Sessão e LLM_Service Compartilhados
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from sessao import obter_sessao, atualizar_sessao
from llm_service import consultar_llm

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
        return "erro_db"

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

    if sub_estado == "MENU":
        # Check para mensagem silenciosa se for a primeira após transferencia
        if sessao.get("voltou_da_entrevista") is True:
            sessao["voltou_da_entrevista"] = False
            # Retorna a mensagem inicial do menu sem precisar classificar a palavra que fez a transicao
            resposta_texto = "Vamos falar de crédito. Posso consultar seu limite ou analisar um pedido de aumento. (Consultar limite, Aumentar limite)"
            sessao["historico"].append({"role": "assistant", "content": resposta_texto})
            return SaidaChat(resposta=resposta_texto, acao="continuar", id_sessao=id_sessao)

        # Classificar se é consulta, aumento ou encerramento
        instrucao = """
        Você é um classificador de intenções para um agente de crédito.
        Classifique a intenção atual do usuário em UMA das opções exatas abaixo:
        - consultar_limite (ver saldo, quanto tenho, limite atual)
        - aumentar_limite (pedir mais, aumentar, novo limite, solicitação de aumento)
        - encerrar (sair, tchau, obrigado, fim, cancelar, não quero)
        - voltar (voltar pro menu principal, triagem, opções globais, outros serviços)
        - outros
        
        Regra: Responda APENAS com o nome da categoria exata. Sem frases.
        """
        intencao = consultar_llm(mensagem, sessao.get("historico", []), instrucao)

        # Limpeza para modelos locais
        intencao = intencao.strip().lower()
        if "aumentar" in intencao or "solicita" in intencao: intencao = "aumentar_limite"
        elif "consultar" in intencao or "ver" in intencao or "saldo" in intencao: intencao = "consultar_limite"
        elif "encerra" in intencao or "sair" in intencao or "tchau" in intencao: intencao = "encerrar"
        elif "volta" in intencao or "menu" in intencao or "serviço" in intencao or "outro" in intencao: intencao = "voltar"
        
        print(f"DEBUG CRÉDITO (Menu): Mensagem '{mensagem}' classificada como '{intencao}'")

        if "erro_llm" in intencao:
            resposta_texto = "Meu classificador está passando por instabilidades temporárias. Tente novamente em alguns segundos."
            # Mantém MENU
        elif "consultar" in intencao:
            resposta_texto = f"Seu limite atual é R$ {limite_atual:.2f}. Posso ajudar em algo mais? (Aumentar limite, Outros serviços)"
            # Mantém MENU
        
        elif "aumentar" in intencao:
            resposta_texto = "Qual o valor de limite desejado? (Ex: 5000)"
            sessao["sub_estado_credito"] = "AGUARDANDO_VALOR"
        
        elif intencao == "encerrar":
            resposta_texto = "Entendido. Atendimento encerrado."
            sessao["estado"] = "ENCERRADO"
            acao = "encerrar"

        elif intencao == "voltar":
            resposta_texto = ""
            sessao["sub_estado_credito"] = "MENU"
            acao = "transferir"
            alvo = "AgenteTriagem"

        else:
             resposta_texto = "Por favor, escolha uma opção para créditos: (Consultar limite, Aumentar limite, Outros serviços)"


    elif sub_estado == "AGUARDANDO_VALOR":
        # Verificação rápida se o usuário desistiu de dar o valor
        instrucao = """
        O bot perguntou qual o valor do limite desejado. O usuário respondeu.
        Classifique em:
        - encerrar (se o usuário desistiu de tudo e quer sair do banco, cancelar)
        - voltar (se o usuário decidiu ver outros serviços do banco, opções globais, triagem)
        - continuar (se for qualquer outra coisa, como um número ou um texto que parece o envio de um valor)
        
        Responda APENAS com a categoria exata.
        """
        intencao_saida = consultar_llm(mensagem, sessao.get("historico", []), instrucao).strip().lower()
        if "erro_llm" in intencao_saida:
            resposta_texto = "Desculpe, falha na interpretação da sua mensagem. Qual seria o valor?"
            return SaidaChat(resposta=resposta_texto, acao="continuar", id_sessao=id_sessao)
        elif "encerra" in intencao_saida or "sair" in intencao_saida:
            resposta_texto = "Operação cancelada. Atendimento encerrado."
            sessao["estado"] = "ENCERRADO"
            sessao["sub_estado_credito"] = "MENU"
            return SaidaChat(resposta=resposta_texto, acao="encerrar", id_sessao=id_sessao)
        elif "volta" in intencao_saida or "menu" in intencao_saida or "serviço" in intencao_saida or "outro" in intencao_saida:
            resposta_texto = ""
            sessao["sub_estado_credito"] = "MENU"
            return SaidaChat(resposta=resposta_texto, acao="transferir", alvo="AgenteTriagem", id_sessao=id_sessao)

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
            
            if aprovado == "erro_db":
                resposta_texto = "Nosso serviço de consulta de scores está temporariamente indisponível. Desculpe-nos. (Outros serviços)"
                sessao["sub_estado_credito"] = "MENU"
            else:
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
                    resposta_texto = f"Solicitação APROVADA baseada no seu score ({score_atual}). Novo limite: R$ {novo_limite:.2f}."
                    cliente["limite_credito"] = novo_limite 
                else:
                    resposta_texto = ("Seu score não aprova este aumento automático. "
                                      "Deseja fazer uma entrevista rápida para atualizar dados e tentar novamente? (Sim, Não)")
                    atualizar_sessao(id_sessao, "sub_estado_credito", "OFERECER_ENTREVISTA")
                    sessao["sub_estado_credito"] = "OFERECER_ENTREVISTA"
        else:
             resposta_texto = "Valor não identificado. Digite apenas o número (ex: 5000)."

    elif sub_estado == "OFERECER_ENTREVISTA":
        msg_lower = mensagem.strip().lower()
        if msg_lower in ["sim", "sim.", "s", "quero", "claro", "aceito", "bora"]:
            intencao = "sim"
        elif msg_lower in ["não", "nao", "n", "não.", "depois", "nunca"]:
            intencao = "nao"
        else:
            instrucao = """
            O agente ofereceu uma entrevista ("Quer fazer uma entrevista? Responda sim ou não").
            O usuário respondeu. Classifique em UMA das opções exatas abaixo:
            - sim (aceitou, quer fazer, ok, bora)
            - nao (recusou, não quer, depois, ah não)
            - encerrar (desistiu de falar, tchau, cancelar o atendimento como um todo)
            - voltar (ver outros serviços, falar com triagem)
            
            Responda APENAS a categoria exata.
            """
            intencao = consultar_llm(mensagem, sessao.get("historico", []), instrucao)
            intencao = intencao.strip().lower()

        if "erro_llm" in intencao:
            resposta_texto = "Desculpe, meu classificador falhou. Deseja iniciar a entrevista? (Sim, Não)"
        elif "sim" in intencao:
            resposta_texto = "" # Não envia mensagem, apenas transfere
            acao = "transferir"
            alvo = "AgenteEntrevista"
            sessao["sub_estado_credito"] = "MENU" # Limpa estado
        elif "encerra" in intencao or "sair" in intencao:
            resposta_texto = "Operação cancelada. Atendimento encerrado."
            sessao["sub_estado_credito"] = "MENU"
            sessao["estado"] = "ENCERRADO"
            acao = "encerrar"
        elif "volta" in intencao or "menu" in intencao or "serviço" in intencao or "outro" in intencao:
            resposta_texto = ""
            sessao["sub_estado_credito"] = "MENU"
            acao = "transferir"
            alvo = "AgenteTriagem"
        else:
            resposta_texto = "Tudo bem. Mais alguma demanda de crédito? (Consultar limite, Aumentar limite, Outros serviços)"
            sessao["sub_estado_credito"] = "MENU"

    return SaidaChat(
        resposta=resposta_texto,
        acao=acao,
        alvo=alvo,
        id_sessao=id_sessao
    )
