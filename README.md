# 🏦 Banco Ágil - Assistente IA (Tech For Humans)

Bem-vindo ao repositório do **Banco Ágil**, um sistema inteligente e multi-agente focado no atendimento bancário via chat, desenvolvido para atender ao **Desafio Técnico para Desenvolvedor de Agente de IA da Tech For Humans**.

Este projeto simula uma assistente virtual conversacional avançada. O usuário interage com um bot que parece unificado ("Single-Agent Illusion"), mas que arquiteturalmente roda através de um sistema Multi-Agent (Routing) orquestrado por LLM local.

---

## 📖 Visão Geral do Projeto

A aplicação provém uma interface de chat intuitiva e veloz onde o cliente pode se autenticar e realizar consultas bancárias cotidianas. Ao invés de fluxos de navegação estáticos e presos a menus numéricos (como URAs telefônicas), o projeto se baseia em **Inferência de Intenção via NLP (Natural Language Processing)**. 

O cliente pode digitar em linguagem natural o que deseja (ex: "Quero ver a cotação do dólar" ou "Meu limite tá baixo, posso aumentar?") e o cérebro principal roteia e processa o pedido. Se o pedido for aumentar o limite e o Score não for forte o suficiente, a IA dinamicamente engatilha uma entrevista contextual para extrair os dados financeiros brutos do indivíduo (renda, dividas, dependentes), re-avaliar o grau de risco (Score) num arquivo em banco de dados e aplicar o aumento no limite.

---

## 🏗 Arquitetura do Sistema e Fluxos

O Back-end foi construído em arquitetura modular utilizando **Python e FastAPI**. O ecossistema é quebrado da seguinte forma lógica:

### ✅ 1. Roteamento e Agentes Independentes (`api/routers/`)
Para evitar código "Spaghetti", o core de negócio foi segmentado em 4 Agentes Autônomos (Micro-Bots):

- **Agente de Triagem (`triagem.py`)**: Recepcionista do banco. Autentica via CPF e Data de Nascimento (`clientes.csv`). Capta a primeira mensagem de necessidade do cliente ("O que deseja fazer?") e realiza o Parsing usando LangChain para transferi-lo de forma implícita e sorrateira para o Agente especialista responsável.
- **Agente de Crédito (`credito.py`)**: Gerencia consultas de saldo e requisições de aumento. Consulta e consolida regras de negócio puras (ex: "Score atual de 300 permite no máximo R$2.000 de limite?"). Se necessário, transfere o contexto para o agente de entrevista.
- **Agente de Entrevista (`entrevista.py`)**: Atuando como Perito em Risco. Faz uma entrevista humanizada perguntando de ocupação profissional até volume de dependentes. Utiliza **Extrativismo Estruturado de Dados** com o LangChain (`JsonOutputParser`) para capturar respostas vagas textuais e converter em JSON estrito. Executa a fórmula de recálculo de Score e grava num pseudo-banco de dados estático. Transfere os resultados de volta ao crédito.
- **Agente de Câmbio (`cambio.py`)**: Consome a API REST externa (AwesomeAPI) sob demanda. Puxa do LLM a entidade "Nome de Moeda", converte para as 3 Letras ISO Globais (ex: 'Libra' -> 'GBP') e devolve uma cotação instantânea versus BRL.

### ✅ 2. Serviços Globais 
- **LLM Service (`api/llm_service.py`)**: Central controladora do LangChain que consome o **Ollama (Llama 3.2)** para todos os subagentes. Suporta Prompt Engineering centralizado e Try/Catch preventivos de *Fallback* para quando a rede/IA falhar.
- **Session Service (`api/sessao.py`)**: Atua como uma memória RAM/Cache "In-Memory" para interações do front. Armazena o ID da aba, histórico de chat (`Role: Content`) para fornecer Context Window à LLM e Variáveis de Estado (Máquina de Estados de conversação - `AGUARDANDO_VALOR`, `MENU`, `AUTENTICADO`).

---

## 🚀 Funcionalidades Implementadas

- **Autenticação em Dois Passos**: Exige Validação sequencial do CPF (apenas 11 dígitos, ignorando pontuação na interface) seguido de Data de Nascimento.
- **Cotação de Moedas em Tempo Real**: Uso de API Pública gratuita ("AwesomeAPI") baseada na identificação da intenção monetária ("Quanto está o BTC?").
- **Workflow de Recálculo Concedido de Limite**: Abordagem inteligente onde um score ruim não encerra a jornada precocemente, mas permite segunda chance via análise de viabilidade atual (Entrevista).
- **Single-Agent Illusion**: Botões baseados em 'Outros Serviços'. Os roteamentos técnicos (`acao: transferir, alvo: AgenteCredito`) não são revelados ao usuário, parecendo uma conversa fluida num único cérebro virtual inteligente.
- **Resiliência de Hardware e Quedas (Try/Catch)**: Sistema tolerante a desastres, capturando exceções geradas por arquivos corrompidos baseados em travas (CSVs abertos) e travamentos bruscos do Backend Local AI (Ollama demorando para responder gera tratativa customizada ao invés de tela congelada).
- **Interface Front-end (UI/UX)**: Layout desacoplado com Dark Mode minimalista "Tech for Humans". Utilização massiva de Quick-Replies interativos e balão emulativo de digitação assíncrono (Typing Indicator).

---

## ⚔ Desafios Enfrentados e Soluções

1. **Race Condition na Classificação de Intenções (Alucinação)**:
   - *Desafio*: O Llama (Open-Source e leve) frequentemente gosta de dar explicações. Na hora da Triagem para pedir para cotar moeda, ele dizia *"Sua intenção não é Entrevista. Vejo que quer uma cotação de moedas (Câmbio)"*. O sistema Python, por ter lido primeiro a palavra *"Entrevista"*, errava em 10% dos casos a rota.
   - *Solução*: Alterada a heurística de varredura Python (Apenas "if palavra in intenção"). Foi construída uma matriz Array iterável que para no momento (`break`) que acha o primeiro Match correspondente explícito sem pegar os ruidos residuais do Output da LLM.

2. **Extração de Dados Imprecisos durante a Entrevista**:
   - *Desafio*: O prompt extraía "Possui dividas?" como "sim, tenho" ou "ñ". Isso quebrava o parser Json e não alimentava os cálculos do novo de Score.
   - *Solução*: Implementado o `JsonOutputParser` nativo do framework **LangChain** garantindo output JSON Strict, formatando a temperatura em `0.0` e usando chaves "Null", unindo a Fallbacks do Python ("Se não vier emprego Formal, limpa e força na raça Autônomo ou None...").

3. **Demora excessiva para responder no front-end**:
   - *Desafio*: Para cada letra ou botão clicado, o bot visual parecia "travado" ou recarregava inteiramente o index.html antes do robô trazer uma resposta, dando sensação de que o servidor era quebrado.
   - *Solução*: Refatoração da mecânica do DOM com chamadas JavaScript puras `Fetch API` para não dar refresh na página e injeção do div `Typing Indicator` enquanto se aguarda o sinal do status-code 200 do FastAPI.

---

## 🛠 Escolhas Técnicas e Justificativas

- **FastAPI**: Escolhido pelo baixo overhead e pelo assincronismo (`async def`) nativo, o que é mandatório ao aguardar um processo extremamente lento como chamadas de LLM ou chamadas HTTP para Cotação. Também possui auto-documentação e roteador simples (`APIRouter`) ideal pra nossa separação em Agentes.
- **Vanilla JS + HTML + CSS**: Foi preterido o uso de ReactJS ou Vue. Como sendo um desafio prático focado na IA, uma aplicação robusta frontend puro garante ausência de dependências NPM inchadas (`node_modules`), sendo só dar F5 e ver funcionando sem atritos de instalação Webpack/Vite para os avaliadores.
- **Ollama / Llama-3.2**: A escolha de uma Stack `Local-First` foi intencional para provar proficiência de ponta a ponta que independe da conta corporativa das OpenAI. O modelo "Llama 3.2" é performático, pode rodar até em modesto hardware caseiro e exibe raciocínio de alto nível.
- **LangChain**: Excelente em lidar com "Output Resolvers" e encadear mensagens contextuais em templates variáveis (Pipeline Chain -> `prompt | llm | string_parser`).
- **Arquivos CSV como DB**: Opção amigável e puramente simulativa para não impor que o time técnico Tech for Humans necessite ligar containers Docker PostgreSQL na avaliação.

---

## 🕹 Tutorial de Execução e Testes

### Pré-requisitos
Ter instalado no sistema operacional:
- **Python 3.10+**
- **Ollama** (para rodar a IA localmente sem chave da OpenAI). Baixe em: `https://ollama.com`

### 1. Preparando o Ambiente (Backend)
1. Clone este repositório para seu ambiente local.
2. Na raiz da pasta, crie um ambiente virtual (Opcional, mas recomendado):
   ```bash
   python -m venv venv
   # Ative-o:
   # No Windows: venv\Scripts\activate
   # No Mac/Linux: source venv/bin/activate
   ```
3. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

### 2. Baixando o Modelo de Inteligência Artificial Local
Inicie o processo do seu "Motor" Ollama no terminal para puxar o cérebro usado em nosso Agente:
```bash
ollama run llama3.2
```
*Se for a primeira vez, ele irá baixar o modelo (cerca de 2GB).* Assim que iniciar um prompt shell `>>>`, pode fechá-lo (Ctrl+D), o modelo já estará armazenado e seu hardware habilitado para ouvi-lo.

### 3. Rodando a Aplicação
Dentro da pasta `api/` execute o servidor ASGI Uvicorn:
```bash
cd api
python main.py
```
O console deverá mostrar o servidor rodando em `http://0.0.0.0:8000`.

### 4. Abrindo o Chat e Testando
Nenhum compilador adicional front-end é requerido!
Basta encontrar o arquivo `index.html` na pasta `/frontend` e abri-lo clicando duas vezes no seu navegador de preferência (Chrome, Edge, etc).

* **Teste 1 (Autenticação)**: Envie o CPF de John Doe simulado no CSV `12345678901`, informando `01/01/1990` na Data.
* **Teste 2 (Câmbio)**: Clique em opções/digite "Gostaria de cotar o USD". 
* **Teste 3 (Roteamento de Entrevista Elevada)**: Com John Doe, peça para *Solicitar Aumento*, Peça a quantidade esbanjadora de `6500` reais. O limite será rejeitado por score baixo. Aceite a entrevista, dê informações como *Ocupação Formal*, *Renda alta*, e *Nenhuma dívida*. Observe o Score subir em tempo real e em seguida refaça a requisição do crédito e colha os frutos do aprovação.