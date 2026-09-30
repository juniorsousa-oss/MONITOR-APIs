# MONITOR DE APIs · SETTA

Central operacional para monitoramento contínuo das APIs e centralização dos relatórios que alimentam os aplicativos SETTA.

## Módulos

### Monitor de APIs
- cartões individuais por integração;
- status ONLINE, ATENÇÃO, OFFLINE e DESATIVADA;
- HTTP, latência, uptime de 24h e falhas consecutivas;
- histórico das verificações;
- incidentes e normalização automática;
- cadastro de endpoints sem gravar tokens no GitHub;
- atualização visual automática do painel.

### Banco de Dados
- fontes centrais compartilhadas;
- upload de Excel, CSV, XML, TXT e JSON;
- histórico das cargas;
- quantidade de registros detectada para Excel/CSV;
- armazenamento central em Supabase Storage quando configurado.

## Arquitetura 24/7

O Streamlit é apenas a interface. O arquivo `monitor_worker.py` executa as verificações independentemente do navegador.

```text
APIs -> monitor_worker.py -> Supabase -> Streamlit
                                   |
                                   -> Central de Dados
```

Para produção, o worker deve permanecer ativo 24 horas por dia. O `render.yaml` já separa o serviço web do worker.

## Execução local

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Em outro terminal:

```bash
python monitor_worker.py --loop --interval 60
```

Sem Supabase o projeto entra em modo local de validação e grava dados em `.runtime/`. Este modo é apenas para testes de interface e fluxo.

## Supabase

1. Crie ou selecione o projeto Supabase.
2. Execute `supabase_schema.sql` no SQL Editor.
3. Configure `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY`.

A SERVICE_ROLE_KEY deve existir apenas no backend.

## APIs autenticadas

No cadastro da API, o campo **Referência do segredo** recebe o nome de uma variável de ambiente, por exemplo `PROTHEUS_API_HEADERS`.

O valor pode ser um token simples ou um JSON de headers. Nenhum token é salvo na tabela de cadastro.

## Render

O `render.yaml` cria:
- `setta-monitor-apis`: interface Streamlit;
- `setta-monitor-worker`: worker contínuo com ciclo de 60 segundos.

Os dois serviços devem receber as mesmas variáveis do Supabase.
