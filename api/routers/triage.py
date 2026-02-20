from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import os
import re
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv

# Importar Sessão Compartilhada
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from sessao import obter_sessao, criar_sessao, atualizar_sessao

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

# Configuração LLM
MAX_TENTATIVAS = 3
ARQUIVO_DADOS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "clientes.csv")

def obter_llm():
    chave_api = os.getenv("GOOGLE_API_KEY")
    if not chave_api:
        raise ValueError("A variável de ambiente GOOGLE_API_KEY não foi definida.")
    return ChatGoogleGenerativeAI(
        google_api_key=chave_api,
        model="gemini-3-flash-preview",
        temperature=0.0
    )

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
        return False, None

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
            "agente_atual": "triagem"
        })
    
    estado = sessao["estado"]
    # ... (resto da lógica usa 'sessao' localmente, que é referencia ao dict, entao funciona)
    resposta_texto = ""
    acao = "continuar"
    alvo = None

    # Máquina de Estados
    if estado == "SAUDACAO":
        resposta_texto = "Olá! Bem-vindo ao Banco Ágil. Sou seu assistente virtual. Para começarmos, por favor, informe seu CPF."
        sessao["estado"] = "AGUARDANDO_CPF"
    
    elif estado == "AGUARDANDO_CPF":
        # Extrai apenas dígitos
        digitos = re.findall(r'\d', mensagem)
        
        if len(digitos) == 11:
            sessao["cpf_temp"] = "".join(digitos)
            resposta_texto = "Obrigado. Agora, por favor, informe sua data de nascimento (DD/MM/AAAA)."
            sessao["estado"] = "AGUARDANDO_DATA_NASCIMENTO"
        else:
            resposta_texto = "CPF inválido. Por favor, digite um CPF válido (11 dígitos, apenas números)."
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
                resposta_texto = f"Autenticação realizada com sucesso, {cliente['nome']}! Em que posso ajudar hoje? (Crédito, Câmbio, Entrevista)"
            else:
                sessao["tentativas"] += 1
                if sessao["tentativas"] >= MAX_TENTATIVAS:
                    resposta_texto = "Não foi possível autenticar seus dados após 3 tentativas. O atendimento será encerrado. Obrigado."
                    acao = "encerrar"
                    sessao["estado"] = "ENCERRADO"
                else:
                    restantes = MAX_TENTATIVAS - sessao["tentativas"]
                    resposta_texto = f"Dados incorretos. Você tem mais {restantes} tentativas. Por favor, informe o CPF novamente."
                    sessao["estado"] = "AGUARDANDO_CPF" # Reinicia fluxo de autenticação
        else:
             resposta_texto = "Data inválida ou formato incorreto. Por favor, use o formato DD/MM/AAAA."

    elif estado == "AUTENTICADO":
        # Classificação de Intenção com LangChain
        try:
             llm = obter_llm()
             prompt = ChatPromptTemplate.from_template("""
                Você é um classificador de intenções bancárias.
                O usuário disse: "{input}"
                
                Classifique nas seguintes categorias:
                - credito (aumento de limite, consultar limite)
                - entrevista (atualizar dados, score, renda)
                - cambio (moeda, cotação, dolar, euro)
                - outros (assuntos gerais)
                
                Responda APENAS com a categoria (credito, entrevista, cambio, outros).
            """)
             chain = prompt | llm | StrOutputParser()
             intencao = chain.invoke({"input": mensagem}).strip().lower()
             
             if "credito" in intencao:
                 resposta_texto = "Entendido. Vou transferi-lo para nosso especialista em Crédito."
                 acao = "transferir"
                 alvo = "AgenteCredito"
             elif "entrevista" in intencao:
                 resposta_texto = "Certo. Vou direcioná-lo para atualização cadastral."
                 acao = "transferir"
                 alvo = "AgenteEntrevista"
             elif "cambio" in intencao:
                 resposta_texto = "Ok. Vamos falar com o especialista em Câmbio."
                 acao = "transferir"
                 alvo = "AgenteCambio"
             else:
                 resposta_texto = "Desculpe, não entendi bem. Poderia reformular? Posso ajudar com Crédito, Câmbio ou Atualização de Cadastro."
                 # Mantém estado AUTENTICADO
        except Exception as e:
             resposta_texto = f"Erro ao processar sua solicitação: {str(e)}"

    elif estado == "ENCERRADO":
        resposta_texto = "Este atendimento já foi encerrado."
        acao = "encerrar"

    return SaidaChat(
        resposta=resposta_texto,
        acao=acao,
        alvo=alvo,
        id_sessao=id_sessao
    )
