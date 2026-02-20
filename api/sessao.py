from threading import Lock

# Gerenciador de Sessões Compartilhado (Thread-Safe para simulação)
# Estrutura: {id_sessao: {estado, dados_cliente, agente_atual, historico}}
SESSOES = {}
LOCK_SESSOES = Lock()

def obter_sessao(id_sessao):
    with LOCK_SESSOES:
        return SESSOES.get(id_sessao)

def criar_sessao(id_sessao, dados_iniciais):
    with LOCK_SESSOES:
        SESSOES[id_sessao] = dados_iniciais
        return SESSOES[id_sessao]

def atualizar_sessao(id_sessao, chave, valor):
    with LOCK_SESSOES:
        if id_sessao in SESSOES:
            SESSOES[id_sessao][chave] = valor
            return True
        return False
