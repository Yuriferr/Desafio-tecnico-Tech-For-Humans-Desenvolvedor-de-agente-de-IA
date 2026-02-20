from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import os
from dotenv import load_dotenv
import re

# Importar Sessão e LLM_Service Compartilhados
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from sessao import obter_sessao, atualizar_sessao
from llm_service import consultar_llm

# Configuração
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
router = APIRouter(prefix="/entrevista", tags=["Agente de Entrevista"])

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
ARQUIVO_DADOS = os.path.join(PASTA_DADOS, "clientes.csv")

def extrair_valor_financeiro(mensagem):
    # Procura por números no formato 0000 ou 0000.00 ou 0.000,00
    numeros = re.findall(r"[\d\.,]+", mensagem)
    if numeros:
        for num_str in numeros:
            clean_str = num_str
            if ',' in clean_str and '.' in clean_str:
                clean_str = clean_str.replace('.', '').replace(',', '.')
            elif ',' in clean_str:
                clean_str = clean_str.replace(',', '.')
            try:
                val = float(clean_str)
                if val >= 0:
                    return val
            except:
                continue
    return -1.0 # Indica falha

def atualizar_score_cliente_csv(cpf, novo_score):
    try:
        df = pd.read_csv(ARQUIVO_DADOS, dtype=str)
        cpf_limpo_alvo = "".join([c for c in cpf if c.isdigit()])
        
        # Cria coluna temporária
        df['cpf_limpo'] = df['cpf'].apply(lambda x: "".join([c for c in str(x) if c.isdigit()]))
        
        if cpf_limpo_alvo in df['cpf_limpo'].values:
            # Atualiza o score na linha onde encontrou o CPF
            idx = df[df['cpf_limpo'] == cpf_limpo_alvo].index
            df.loc[idx, 'score'] = str(novo_score)
            df = df.drop(columns=['cpf_limpo']) # Remove a coluna temporária
            df.to_csv(ARQUIVO_DADOS, index=False)
            return True
        return False
    except Exception as e:
        print(f"Erro ao atualizar CSV de clientes: {e}")
        return "erro_db"

@router.post("/", response_model=SaidaChat)
async def endpoint_entrevista(entrada: EntradaChat):
    id_sessao = entrada.id_sessao
    mensagem = entrada.mensagem.strip().lower()
    
    sessao = obter_sessao(id_sessao)
    if not sessao or not sessao.get("dados_cliente"):
        return SaidaChat(
            resposta="Sessão não encontrada ou não autenticada.",
            acao="encerrar",
            id_sessao=id_sessao
        )
    
    # Adicionar mensagem do usuário ao histórico global
    if "historico" not in sessao: sessao["historico"] = []
    sessao["historico"].append({"role": "user", "content": mensagem})

    # Verifica se acabou de ser transferido e é a primeira chamada neste agente
    estado_entrevista = sessao.get("sub_estado_entrevista", "INICIO")
    
    # Se ele for inicial, nós ignoramos a entrada do usuário que ativou a transferência
    # e enviamos a pergunta direto!
    if estado_entrevista == "INICIO":
        resposta_texto = ("Vamos atualizar seus dados para reavaliar seu score.\n\n"
                          "Informe os seguintes dados (pode ser em uma única mensagem):\n"
                          "- Renda mensal\n"
                          "- Ocupação (Formal, Autônomo, Desempregado)\n"
                          "- Despesas fixas\n"
                          "- Número de dependentes\n"
                          "- Possui dívidas ativas? (Sim, Não)")
        sessao["sub_estado_entrevista"] = "COLETANDO_DADOS"
        sessao["dados_entrevista"] = {
            "renda": None,
            "emprego": None,
            "despesas": None,
            "dependentes": None,
            "dividas": None
        }
        sessao["historico"].append({"role": "assistant", "content": resposta_texto})
        return SaidaChat(resposta=resposta_texto, acao="continuar", id_sessao=id_sessao)

    resposta_texto = ""
    acao = "continuar"
    alvo = None

    if estado_entrevista == "COLETANDO_DADOS":
        instrucao = """
        Você é um assistente especializado em extrair informações financeiras em formato JSON.
        Se um dado não foi informado agora ou no histórico recente, coloque o valor como null.
        
        Estrutura exigida do JSON:
        - "renda": número (float) do salário/rendimento mensal, ou null
        - "emprego": exatamente "formal", "autônomo" ou "desempregado", ou null
        - "despesas": número (float) do custo fixo mensal, ou 0.0 caso diga que "não tem despesas", "0 despesas", "sem despesas", senão null
        - "dependentes": string Exatamente "0" (se disser que não tem, nenhum, sem dependentes), "1", "2" ou "3+", ou null se não falado
        - "dividas": string "sim" ou "não" (mesmo se "sem dívidas", colocar "não"), ou null
        - "encerrar": boolean (true se desiste do banco inteiro, tchau, quer sair)
        - "voltar": boolean (true se apenas quer voltar para o menu inicial, opções globais, triagem)
        
        Importante: Responda APENAS com o JSON. Não adicione nenhum texto antes ou depois.
        Exemplo de continuação comum:
        {"renda": 5000.0, "emprego": "formal", "despesas": 0.0, "dependentes": "0", "dividas": "não", "encerrar": false, "voltar": false}
        """
        dados_extraidos = consultar_llm(mensagem, sessao.get("historico", []), instrucao, formato="json")
        
        # Verificar cancelamento imediato ou retorno ao menu pela IA
        if isinstance(dados_extraidos, dict):
            if dados_extraidos.get("erro_llm") is True:
                resposta_texto = "Desculpe, meu sistema falhou ao interpretar suas informações. Poderia enviá-las de novo?"
                return SaidaChat(resposta=resposta_texto, acao="continuar", id_sessao=id_sessao)
                
            if dados_extraidos.get("voltar") is True:
                resposta_texto = ""
                sessao["sub_estado_entrevista"] = "INICIO"
                return SaidaChat(resposta=resposta_texto, acao="transferir", alvo="AgenteTriagem", id_sessao=id_sessao)
            
            if dados_extraidos.get("encerrar") is True:
                resposta_texto = "Entrevista cancelada. Atendimento encerrado."
                sessao["sub_estado_entrevista"] = "INICIO"
                sessao["estado"] = "ENCERRADO"
                sessao["historico"].append({"role": "assistant", "content": resposta_texto})
                return SaidaChat(resposta=resposta_texto, acao="encerrar", id_sessao=id_sessao)
        
        # Merge de dados já obtidos com os novos
        dados_acumulados = sessao.get("dados_entrevista", {})
        
        # Verifica e atualiza apenas os novos dados extraídos com sucesso
        import re as regex_module
        if isinstance(dados_extraidos, dict):
            # Extração defensiva com Regex direta da mensagem se o LLM falhar miseravelmente
            numeros = regex_module.findall(r"[\d\.,]+", mensagem)
            val_extraido = None
            if numeros:
                for num_str in numeros:
                     clean_str = num_str
                     if ',' in clean_str and '.' in clean_str:
                         clean_str = clean_str.replace('.', '').replace(',', '.')
                     elif ',' in clean_str:
                         clean_str = clean_str.replace(',', '.')
                     try: val_extraido = float(clean_str); break
                     except: continue

            if dados_extraidos.get("renda") is not None:
                try: dados_acumulados["renda"] = float(dados_extraidos["renda"])
                except: pass
            
            if dados_extraidos.get("despesas") is not None:
                 try: dados_acumulados["despesas"] = float(dados_extraidos["despesas"])
                 except: pass
                 
            # Tratamento avançado de bypass do Fallback (Caso pessoa não indique nominalmente e só sobrar um numero ou mande algo como '0 despesas')
            if "sem despesa" in mensagem.lower() or "não tenho despesa" in mensagem.lower() or "0 despesa" in mensagem.lower():
                dados_acumulados["despesas"] = 0.0
            elif "sem renda" in mensagem.lower() or "0 renda" in mensagem.lower():
                dados_acumulados["renda"] = 0.0
                
            if dados_acumulados.get("renda") is None and val_extraido is not None and "renda" in mensagem.lower():
                dados_acumulados["renda"] = val_extraido
            elif dados_acumulados.get("despesas") is None and val_extraido is not None and "despesa" in mensagem.lower():
                dados_acumulados["despesas"] = val_extraido
            elif val_extraido is not None:
                if dados_acumulados.get("renda") is None and "despesas" in dados_acumulados:
                     dados_acumulados["renda"] = val_extraido
                elif dados_acumulados.get("despesas") is None and "renda" in dados_acumulados:
                     dados_acumulados["despesas"] = val_extraido
            
            emprego = str(dados_extraidos.get("emprego", "")).lower()
            if "formal" in emprego: dados_acumulados["emprego"] = "formal"
            elif "autônomo" in emprego or "autonomo" in emprego: dados_acumulados["emprego"] = "autônomo"
            elif "desempregado" in emprego: dados_acumulados["emprego"] = "desempregado"
            
            dep = str(dados_extraidos.get("dependentes", "")).lower()
            if dep in ["0", "1", "2", "3+"]: dados_acumulados["dependentes"] = dep
            else:
                 # fallback limpeza dependentes baseada puramente na intencao expressa
                 msg_limpa = mensagem.lower()
                 if "3" in msg_limpa or "mais" in msg_limpa or "três" in msg_limpa: dados_acumulados["dependentes"] = "3+"
                 elif "2" in msg_limpa or "dois" in msg_limpa: dados_acumulados["dependentes"] = "2"
                 elif "1" in msg_limpa or "um" in msg_limpa: dados_acumulados["dependentes"] = "1"
                 elif "0" in msg_limpa or "sem dependente" in msg_limpa or "nenhum" in msg_limpa or "nao tem" in msg_limpa.replace("ã","a"): dados_acumulados["dependentes"] = "0"
                 # Se a LLM tentou passar nulo, mas e extraímos que ele disse 0 literalmente "0 dependentes"
                 if dados_acumulados.get("dependentes") is None and val_extraido == 0.0:
                      dados_acumulados["dependentes"] = "0"
            
            div = str(dados_extraidos.get("dividas", "")).lower()
            if "sim" in div: dados_acumulados["dividas"] = "sim"
            elif "não" in div or "nao" in div: dados_acumulados["dividas"] = "não"
            else:
                 msg_limpa = mensagem.lower()
                 if "sem divida" in msg_limpa.replace("í","i") or "nenhuma divida" in msg_limpa.replace("í","i") or "não tenho divida" in msg_limpa.replace("í","i").replace("ã","a"):
                     dados_acumulados["dividas"] = "não"
                 elif "tenho divida" in msg_limpa.replace("í","i") or "estou com divida" in msg_limpa.replace("í","i"):
                     dados_acumulados["dividas"] = "sim"

        sessao["dados_entrevista"] = dados_acumulados
        
        # Checar o que ainda falta
        campos_faltando = []
        if dados_acumulados.get("renda") is None: campos_faltando.append("renda mensal")
        if dados_acumulados.get("emprego") is None: campos_faltando.append("ocupação (formal, autônomo ou desempregado)")
        if dados_acumulados.get("despesas") is None: campos_faltando.append("despesas fixas")
        if dados_acumulados.get("dependentes") is None: campos_faltando.append("número de dependentes")
        if dados_acumulados.get("dividas") is None: campos_faltando.append("se possui dívidas ativas")

        if len(campos_faltando) > 0:
            lista_campos = "\n- " + "\n- ".join(campos_faltando)
            resposta_texto = f"Ainda faltam alguns dados. Informe:\n {lista_campos}"
            # Mantém no estado COLETANDO_DADOS
        else:
            # Todos os dados coletados! Calcular SCORE
            renda = float(dados_acumulados["renda"])
            despesas = float(dados_acumulados["despesas"])
            emprego = dados_acumulados["emprego"]
            dependentes = dados_acumulados["dependentes"]
            dividas = dados_acumulados["dividas"]

            # Fórmula
            peso_renda = 30
            score_base = (renda / (despesas + 1)) * peso_renda
            
            peso_emprego = {"formal": 300, "autônomo": 200, "desempregado": 0}
            score_emprego = peso_emprego.get(emprego, 0)
            
            peso_dependentes = {"0": 100, "1": 80, "2": 60, "3+": 30}
            score_dependentes = peso_dependentes.get(dependentes, 30)
            
            peso_dividas = {"sim": -100, "não": 100}
            score_dividas = peso_dividas.get(dividas, 0)
            
            novo_score = int(score_base + score_emprego + score_dependentes + score_dividas)
            novo_score = max(0, min(1000, novo_score)) # Limita entre 0 e 1000

            # Atualizar Perfil na Sessão
            cliente = sessao["dados_cliente"]
            score_antigo = cliente.get("score")
            cliente["score"] = novo_score
            
            # Atualizar no CSV
            sucesso_db = atualizar_score_cliente_csv(cliente["cpf"], novo_score)
            
            if sucesso_db == "erro_db":
                resposta_texto = "Ocorreu um erro técnico ao salvar seu novo score no banco de dados. Tente novamente mais tarde."
                sessao["sub_estado_entrevista"] = "INICIO"
                return SaidaChat(resposta=resposta_texto, acao="transferir", alvo="AgenteTriagem", id_sessao=id_sessao)

            resposta_texto = (f"Dados atualizados.\n"
                              f"Score recalculado: {score_antigo} ➔ **{novo_score}**.\n"
                              f"Agora podemos prosseguir com o crédito.")
            
            # Limpar estado da entrevista
            sessao["sub_estado_entrevista"] = "INICIO"
            sessao["voltou_da_entrevista"] = True

            acao = "transferir"
            alvo = "AgenteCredito"

    sessao["historico"].append({"role": "assistant", "content": resposta_texto})
    
    return SaidaChat(
        resposta=resposta_texto,
        acao=acao,
        alvo=alvo,
        id_sessao=id_sessao
    )
