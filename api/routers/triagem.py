from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import os
import re
from dotenv import load_dotenv

# Importar Sessão e LLM_Service Compartilhados
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from sessao import obter_sessao, criar_sessao, atualizar_sessao
from llm_service import consultar_llm

# Configuração
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
router = APIRouter(prefix="/triagem", tags=["Agente de Triagem"])

# Modelos
class EntradaChat(BaseModel):
    id_sessao: str
    mensagem: str

class SaidaChat(BaseModel):
    resposta: str
    acao: str = "continuar" # continuar, transferir, encerrar
    alvo: Optional[str] = None # nome do agente se houver transferência
    id_sessao: str

# Configuração GERAL
MAX_TENTATIVAS = 3
ARQUIVO_DADOS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "clientes.csv")

# Lógica de Autenticação
def autenticar_cliente(cpf_usuario, data_usuario):
    """
    Verifica se o CPF e a Data de Nascimento correspondem na base de dados (clientes.csv).
    """
    try:
        # Lê o CSV como string para preservar zeros à esquerda
        df = pd.read_csv(ARQUIVO_DADOS, dtype=str)
        
        # Normaliza o CPF recebido (remove formatação)
        cpf_limpo = "".join([c for c in cpf_usuario if c.isdigit()])
        
        # Cria coluna temporária com CPF limpo para comparação
        df['cpf_limpo'] = df['cpf'].apply(lambda x: "".join([c for c in str(x) if c.isdigit()]))
        
        cliente_encontrado = df[df['cpf_limpo'] == cpf_limpo]
        
        if not cliente_encontrado.empty:
            data_registrada = cliente_encontrado.iloc[0]['data_nascimento']
            # Compara strings (formato DD/MM/AAAA)
            if data_registrada == data_usuario:
                return True, cliente_encontrado.iloc[0].to_dict()
        
        return False, None
    except Exception as e:
        print(f"Erro na autenticação: {e}")
        return False, "erro_db"

@router.post("/", response_model=SaidaChat)
async def endpoint_triagem(entrada: EntradaChat):
    id_sessao = entrada.id_sessao
    mensagem = entrada.mensagem.strip()
    
    # Inicializa Sessão via módulo compartilhado
    sessao = obter_sessao(id_sessao)
    if not sessao:
        sessao = criar_sessao(id_sessao, {
            "estado": "SAUDACAO",
            "tentativas": 0,
            "dados_cliente": None,
            "cpf_temp": None,
            "agente_atual": "triagem",
            "historico": [] # Lista de mensagens {role, content}
        })
    
    estado = sessao["estado"]
    
    # Adicionar mensagem do usuário ao histórico
    if "historico" not in sessao: sessao["historico"] = []
    sessao["historico"].append({"role": "user", "content": mensagem})
    
    # ... (resto da lógica usa 'sessao' localmente, que é referencia ao dict, entao funciona)
    resposta_texto = ""
    acao = "continuar"
    alvo = None

    # Máquina de Estados
    if estado == "SAUDACAO":
        resposta_texto = "Olá! Bem-vindo ao Banco Ágil. Sou o assistente virtual. Informe seu CPF, por favor."
        sessao["estado"] = "AGUARDANDO_CPF"
    
    elif estado == "AGUARDANDO_CPF":
        # Extrai apenas dígitos
        digitos = re.findall(r'\d', mensagem)
        
        if len(digitos) == 11:
            sessao["cpf_temp"] = "".join(digitos)
            resposta_texto = "Obrigado! Agora sua data de nascimento, no formato DD/MM/AAAA."
            sessao["estado"] = "AGUARDANDO_DATA_NASCIMENTO"
        else:
            resposta_texto = "CPF inválido. Certifique-se de digitar 11 dígitos."
            # Mantém no estado atual
            
    elif estado == "AGUARDANDO_DATA_NASCIMENTO":
        # Valida formato da data DD/MM/AAAA
        match_data = re.search(r"\d{2}/\d{2}/\d{4}", mensagem)
        if match_data:
            data_nascimento = match_data.group(0)
            cpf = sessao.get("cpf_temp")
            
            sucesso, cliente = autenticar_cliente(cpf, data_nascimento)
            
            if sucesso:
                sessao["dados_cliente"] = cliente
                sessao["estado"] = "AUTENTICADO"
                resposta_texto = f"Autenticação realizada com sucesso, {cliente['nome']}! Em que posso ajudar hoje? (Crédito, Cotação de Moedas, Atualização Cadastral)"
            elif cliente == "erro_db":
                resposta_texto = "Desculpe, nosso sistema de cadastro está temporariamente indisponível. Por favor, tente novamente mais tarde."
                # Mantém AGUARDANDO_DATA_NASCIMENTO mas não gasta tentativa
            else:
                sessao["tentativas"] += 1
                if sessao["tentativas"] >= MAX_TENTATIVAS:
                    resposta_texto = "Não foi possível autenticar seus dados após 3 tentativas. O atendimento será encerrado. Obrigado."
                    acao = "encerrar"
                    sessao["estado"] = "ENCERRADO"
                else:
                    restantes = MAX_TENTATIVAS - sessao["tentativas"]
                    resposta_texto = f"Dados não conferem. Tentativas restantes: {restantes}. Informe seu CPF novamente."
                    sessao["estado"] = "AGUARDANDO_CPF" # Reinicia fluxo de autenticação
        else:
             resposta_texto = "Data inválida. Use o formato DD/MM/AAAA."

    elif estado == "AUTENTICADO":
        if not mensagem:
             resposta_texto = "Com o que mais posso ajudá-lo hoje? (Crédito, Cotação de Moedas, Atualização Cadastral)"
             sessao["historico"].append({"role": "assistant", "content": resposta_texto})
             return SaidaChat(resposta=resposta_texto, acao="continuar", id_sessao=id_sessao)

        # 1. Correspondência exata rápida (Bypass do LLM para cliques de Quick Reply)
        msg_lower = mensagem.lower()
        if msg_lower in ["crédito", "credito"]:
            intencao = "credito"
        elif msg_lower == "cotação de moedas":
            intencao = "cambio"
        elif msg_lower == "atualização cadastral":
            intencao = "entrevista"
        else:
            # 2. Classificação de Intenção com LangChain através do LLM_Service para texto livre
            try:
                 instrucao = """
                 Você é um classificador de intenções bancárias.
                 Classifique a intenção atual do usuário em UMA das seguintes categorias exatas:
                 - credito (solicitar, consultar, pedir aumento)
                 - entrevista (atualizar cadastro, fazer entrevista)
                 - cambio (cotação de moedas, câmbio, dólar, euro)
                 - encerrar (tchau, fim, não quero)
                 - outros
                 
                 Não dê explicações. Apenas a palavra exata da categoria em letras minúsculas.
                 """
                 intencao_bruta = consultar_llm(mensagem, sessao.get("historico", []), instrucao)
                 
                 # Limpeza extra para modelos locais
                 intencao_bruta = intencao_bruta.strip().lower()
                 
                 # Pega a intenção primária se o LLM tiver respondido uma frase inteira
                 intencao = "outros"
                 if "erro_llm" in intencao_bruta:
                     intencao = "erro_llm"
                 else:
                     for palavra in intencao_bruta.replace(",", " ").replace(".", " ").replace(":", " ").split():
                         if palavra in ["cambio", "câmbio", "cotação", "moeda", "moedas", "dólar", "euro"]:
                             intencao = "cambio"
                             break
                         elif palavra in ["credito", "crédito", "empréstimo", "limite"]:
                             intencao = "credito"
                             break
                         elif palavra in ["entrevista", "cadastro", "atualização"]:
                             intencao = "entrevista"
                             break
                         elif palavra in ["encerrar", "sair", "tchau"]:
                             intencao = "encerrar"
                             break
            except Exception as e:
                 print(f"Excessão não tratada na triagem ao classificar LLM: {e}")
                 intencao = "erro_llm"
             
             
        if "erro_llm" in intencao:
            resposta_texto = "Desculpe, meu sistema de interpretação está indisponível agora. Poderia repetir?"
        elif intencao == "encerrar":
            resposta_texto = "Atendimento encerrado. Obrigado por escolher o Banco Ágil! Até logo."
            acao = "encerrar"
            sessao["estado"] = "ENCERRADO"
        elif "credito" in intencao:
            resposta_texto = "" # Transferência silenciosa
            acao = "transferir"
            alvo = "AgenteCredito"
            sessao["voltou_da_entrevista"] = True # Força o agente a enviar a primeira msg
        elif "entrevista" in intencao:
            resposta_texto = "" # Transferência silenciosa
            acao = "transferir"
            alvo = "AgenteEntrevista"
        elif "cambio" in intencao:
            resposta_texto = "" # Transferência silenciosa
            acao = "transferir"
            alvo = "AgenteCambio"
            sessao["iniciando_cambio"] = True
        else:
            resposta_texto = "Poderia reformular? Atendo demandas sobre (Crédito, Cotação de Moedas, Atualização Cadastral)."
            # Mantém estado AUTENTICADO

    elif estado == "ENCERRADO":
        resposta_texto = "Este atendimento já foi encerrado."
        acao = "encerrar"

    sessao["historico"].append({"role": "assistant", "content": resposta_texto})
    
    return SaidaChat(
        resposta=resposta_texto,
        acao=acao,
        alvo=alvo,
        id_sessao=id_sessao
    )
