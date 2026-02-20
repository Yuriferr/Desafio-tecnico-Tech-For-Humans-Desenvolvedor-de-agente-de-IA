from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import os
import requests
from dotenv import load_dotenv

# Importar Sessão e LLM_Service Compartilhados
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from sessao import obter_sessao
from llm_service import consultar_llm

# Configuração
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
router = APIRouter(prefix="/cambio", tags=["Agente de Câmbio"])

# Modelos
class EntradaChat(BaseModel):
    id_sessao: str
    mensagem: str

class SaidaChat(BaseModel):
    resposta: str
    acao: str = "continuar" 
    alvo: Optional[str] = None
    id_sessao: str

def obter_cotacao(moeda_origem: str, moeda_destino: str = "BRL"):
    """
    Busca a cotação real usando a API pública e gratuita 'AwesomeAPI'.
    """
    url = f"https://economia.awesomeapi.com.br/last/{moeda_origem}-{moeda_destino}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            dados = response.json()
            chave = f"{moeda_origem}{moeda_destino}"
            
            if chave in dados:
                info = dados[chave]
                nome = info.get('name', '')
                valor = float(info.get('bid', 0)) # Preço de compra
                return True, nome, valor
    except Exception as e:
        print(f"Erro ao buscar cotação de {moeda_origem}: {e}")
        
    return False, "Erro ao consultar a API", 0.0

@router.post("/", response_model=SaidaChat)
async def endpoint_cambio(entrada: EntradaChat):
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
    
    # Se a mensagem for vazia, significa transferência, envia saudação
    if not mensagem:
        resposta_texto = "Perfeito, vamos falar sobre cotação das moedas. Sobre qual moeda deseja pesquisar?"
        sessao["sub_estado_cambio"] = "AGUARDANDO_MOEDA"
        sessao["historico"].append({"role": "assistant", "content": resposta_texto})
        return SaidaChat(resposta=resposta_texto, acao="continuar", id_sessao=id_sessao)

    sessao["historico"].append({"role": "user", "content": mensagem})

    sub_estado = sessao.get("sub_estado_cambio", "MENU")
    
    resposta_texto = ""
    acao = "continuar"
    alvo = None

    if sub_estado == "MENU" or sub_estado == "AGUARDANDO_MOEDA":
        # Processar IA para extrair a moeda ou intenção de sair
        instrucao = """
        Você é um atendente de câmbio.
        O cliente pediu uma cotação. Extraia o código ISO da moeda desejada com exatas 3 letras maiúsculas.
        Exemplo de siglas: USD para Dólar, EUR para Euro, GBP para Libra, BTC para Bitcoin.
        Se ele quiser consultar o Real para o Dólar, extraia "USD".
        
        Se o usuário quiser sair ou encerrar o banco inteiro, retorne exatamente "SAIR".
        Se o usuário quiser ver outros serviços e falar com outros agentes, retorne exatamente "VOLTAR".
        Se você não identificar nenhuma moeda com clareza, retorne "DESCONHECIDO".

        Responda APENAS com a sigla de 3 letras maiúsculas, "SAIR", "VOLTAR" ou "DESCONHECIDO". Nada mais.
        """
        resultado_llm = consultar_llm(mensagem, sessao.get("historico", []), instrucao)
        codigo_moeda = resultado_llm.strip().upper()

        if "ERRO_LLM" in codigo_moeda:
            resposta_texto = "Meu sistema de câmbio está instável. Qual moeda deseja consultar?"
            sessao["sub_estado_cambio"] = "AGUARDANDO_MOEDA"
        elif "SAIR" in codigo_moeda or "ENCER" in codigo_moeda:
            resposta_texto = "Atendimento encerrado."
            sessao["estado"] = "ENCERRADO"
            acao = "encerrar"
        elif "VOLTAR" in codigo_moeda:
            resposta_texto = ""
            sessao["sub_estado_cambio"] = "MENU"
            acao = "transferir"
            alvo = "AgenteTriagem"
        elif codigo_moeda == "DESCONHECIDO" or len(codigo_moeda) != 3:
             resposta_texto = "Moeda não compreendida. Especifique-a, por favor: (Dólar, Euro, Libra)"
             sessao["sub_estado_cambio"] = "AGUARDANDO_MOEDA"
        else:
             # Fazer a busca na API
             sucesso, nome_par, valor = obter_cotacao(codigo_moeda, "BRL")
             
             if sucesso:
                 resposta_texto = f"Cotação de **{nome_par}**: R$ {valor:.4f}. Deseja pesquisar outra moeda? (Outros serviços)"
                 sessao["sub_estado_cambio"] = "AGUARDANDO_MOEDA"
             elif nome_par == "Erro ao consultar a API":
                 resposta_texto = "O provedor de cotações em tempo real está indisponível no momento. Pode tentar mais tarde? (Outros serviços)"
                 sessao["sub_estado_cambio"] = "MENU"
             else:
                 resposta_texto = f"Cotação de {codigo_moeda} indisponível no momento. Deseja tentar outra? (Outros serviços)"
                 sessao["sub_estado_cambio"] = "AGUARDANDO_MOEDA"

    # Salva no histórico
    sessao["historico"].append({"role": "assistant", "content": resposta_texto})

    return SaidaChat(
        resposta=resposta_texto,
        acao=acao,
        alvo=alvo,
        id_sessao=id_sessao
    )
