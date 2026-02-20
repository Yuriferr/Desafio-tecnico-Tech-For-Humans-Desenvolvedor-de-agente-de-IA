# Como Configurar o Ollama Localmente

Para rodar este projeto com a IA local (Ollama), siga os passos abaixo:

## 1. Baixar e Instalar o Ollama
O Ollama é um serviço que precisa ser instalado no sistema operacional.
- Acesse: [https://ollama.com/](https://ollama.com/)
- Baixe a versão para Windows e instale.

## 2. Baixar o Modelo de IA
O código está configurado para usar o modelo `llama3.2` (leve e rápido).
Abra seu terminal (CMD ou PowerShell) e digite:

```bash
ollama run llama3.2
```

Isso irá baixar o modelo (cerca de 2GB) e iniciar o chat. Quando terminar de baixar e abrir o chat, você pode digitar `/bye` para sair, mas deixe o aplicativo Ollama rodando em segundo plano (ícone na barra de tarefas).

## 3. Rodar a API
Agora a API do Banco Ágil irá se conectar automaticamente ao seu Ollama local na porta 11434.

```bash
python api/main.py
```

---
**Nota sobre portabilidade:**
Não é possível colocar o Ollama "dentro da pasta api" para evitar instalação, pois ele é um software complexo que depende de drivers de vídeo e sistema operacional. Cada usuário deve ter o Ollama instalado em sua máquina.
