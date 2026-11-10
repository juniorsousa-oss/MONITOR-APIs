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

## Integração MES GeneralReport (piloto)

A origem fornecida pela SETTA é `GET https://mes.settadigital.com/rest/v1/GeneralReport?Company=01&Branch=0201`.
A API foi informada pelo fornecedor como **Bearer**; o formato da credencial também pode ser compatível com HTTP Basic, o que ainda precisa ser confirmado. A credencial nunca deve aparecer no GitHub, em logs, na URL ou no banco de configurações do monitor.

- `SETTA_MES_GENERAL_REPORT_TOKEN`: valor do Bearer, apenas no ambiente seguro
  que executa a consulta (não incluir o prefixo `Bearer `).
- Autenticação **Bearer confirmada** em execução Postman HTTP 200 (aproximadamente 30 segundos). A antiga variável `SETTA_MES_GENERAL_REPORT_AUTH_SCHEME` é ignorada: ela pode ser removida do Streamlit Secrets. A variável do token deve conter somente seu valor, sem o prefixo `Bearer `.
- `SETTA_MES_GENERAL_REPORT_ENABLED=1`: libera o cadastro ativo do healthcheck.
  Por padrão fica **desativado** enquanto não houver credencial e contrato de dados validados.
- O teste é leve: só lê o início da resposta, sem baixar nem registrar o
  relatório mensal inteiro; recusa redirecionamentos e respostas HTML.
- O Postman do fornecedor apresentou HTTP 200 após ~30s. O monitor usa timeout
  de leitura de até 90s, e alerta de lentidão após 45s; o botão **Reiniciar API**
  executa somente 1 tentativa para evitar sobrecarga desnecessária.
- Erros HTTP 500 em ~0,5s (registrados no Streamlit) não se explicam por timeout:
  a investigação deve comparar a requisição e o ambiente do Streamlit com o
  Postman. O monitor registra somente status, tipo da resposta e, se existir,
  identificador seguro de rastreamento; nunca o conteúdo do erro nem o token.
- O worker Python limita a frequência automática a um teste por 30 minutos
  (consultas manuais são independentes).
- **Importante:** o monitor agendado pelo Supabase `setta-monitor-worker`
  mantém uma lista própria de integrações. A integração externa deve ser
  adicionada também ao worker depois que o segredo for configurado nele.
  Este código não ativa o monitoramento cron do Supabase por si só.
- **Fonte atual preservada:** a carga manual de `relatorio_geral` e o
  pipeline que combina FOR001, FOR022 e CADASTROS permanecem inalterados.
  Antes de habilitar ingestão automática, conferir formato, colunas, chaves,
  datas, volumes e diferenças entre API e último relatório homologado.


## Homologação do conteúdo MES (sem substituir a produção)

No Monitor de APIs, a seção **HOMOLOGAÇÃO — RELATÓRIO GERAL VIA API MES**
permite coletar o JSON integral sob demanda e comparar com a última versão
normalizada da fonte `relatorio_geral` na Central de Dados. Ela não altera
nenhum arquivo, fonte, versão, base derivada ou cálculo de aplicativos.

**Controle de acesso adicional obrigatório:**
`SETTA_MES_GENERAL_REPORT_VALIDATE_PIN` em Streamlit Secrets, com senha
privada de **pelo menos 12 caracteres**, diferente do Bearer Token. A UI só
libera a consulta após digitar essa senha. Não incluir o PIN no GitHub.

- O modo de diagnóstico normal do Monitor continua leve (lê só o início da resposta).
- Na coleta integral há limite de 50 MiB no JSON MES e limites de 55 MiB no
  pacote comprimido e 180 MiB no conteúdo expandido da Central.
- O Relatório Geral validado permanece sendo a planilha anterior; a consulta
  exibe apenas **estatísticas agregadas**, sem números de OP, materiais,
  descrições, lotes, pessoas, token ou respostas brutas.
- A comparação utiliza o par OP + Código; a necessidade é contada uma vez
  por dia de solicitação e o atendimento é somado entre os lotes. Divergências
  de necessidade no mesmo dia são apontadas.
- O período temporal retornado pela API **não está homologado**. Uma divergência
  de total pode representar escopos temporais diferentes, não erro de cálculo.
- Não habilitar sincronização automática ou substituição da fonte enquanto
  a comparação real não estiver aprovada.

## Erros de código de material ausente no JSON MES

Quando a API retorna um registro sem `Code`, a homologação **não deve**
desconsiderar a linha automaticamente. O Monitor realiza auditoria agregada
dos registros recebidos e apresenta:

- Total recebido, total válido e quantos registros têm pendências.
- Contagens por tipo (`CODIGO_AUSENTE`, `OP_AUSENTE`,
  `QUANTIDADE_INVALIDA`, `DATA_INVALIDA` etc.).
- Quantidade de registros **sem código e com quantidade positiva**.
- Até 12 posições do JSON e indicadores de presença (OP, descrição, lote
  e quantidade positiva), sem exibir os valores desses campos.

Apenas objetos integralmente vazios são contabilizados como vazios e
ignorados com segurança. **Qualquer registro não vazio sem Code bloqueia
a comparação com a Central**, inclusive quando traz quantidade zero.
Nenhum material é inventado, somado a outro ou excluído para homologar.
Nenhum dado bruto é salvo, e o MRP continua alimentado pela fonte atual.

## Conciliação de exceções sem código (10/11/2026)

Uma exportação manual do MES (aba `Geral`, **29.605 registros**) e o
JSON consultado pelo Monitor (**29.605 registros**) apresentam a mesma
anomalia estrutural: **1 material sem `Code` e com 1 unidade pendente**.
No Excel, o registro está na linha 27.322; no JSON, na posição 27.321.
É uma inconsistência da origem, não um erro de criação do código pelo Monitor.

Para analisar os outros registros sem perder a informação pendente:

1. Abrir o Monitor → **HOMOLOGAÇÃO — RELATÓRIO GERAL VIA API MES**.
2. Informar a senha privada de homologação.
3. Selecionar o **Excel manual atualizado**, na aba `Geral`, exportado na
   mesma data da API. O arquivo fica apenas em memória nesta sessão.
4. Executar uma única vez **COLETAR E COMPARAR COM O RELATÓRIO ATUAL**.
5. Conferir comparativo de registros **válidos** e as duas auditorias:
   API e Excel. Exceções de código são comparadas pelas demais informações
   apenas para diagnóstico, nunca para inventar um código.
6. Mesmo que os registros válidos coincidam, a homologação integral continua
   **BLOQUEADA** enquanto qualquer material não vazio sem código existir.

Quando o usuário não seleciona Excel manual, a Central de Dados continua sendo
a referência, porém ela pode estar em data diferente da última exportação.
A comparação de referência manual não altera a versão publicada na Central,
as fontes FOR001/FOR022/CADASTROS nem os cálculos do MRP. Nenhum dado de
planilha ou da API é salvo pelo processo de homologação; somente métricas
agregadas são exibidas.

**Regularização definitiva:** o código do material deve ser conferido na
origem MES e, se possível, confrontado com o cadastro oficial antes de
autorizar sincronização automática. Não atribuir código pela descrição apenas.

## Investigação de diferenças API MES × Excel (10/11/2026)

A comparação operacional identificou 45 pares OP/produto exclusivos da API,
23 pares comuns com quantidade diferente e uma exceção sem código presente
nas duas origens. Essa diferença pode decorrer de alterações no MES após a
exportação manual, mas isso **não está confirmado**.

O detalhamento adicional da seção de homologação apresenta:

- Diferença de necessidade, atendimento e pendência decomposta entre
  **somente na API**, **somente no Excel** e **alteração em pares comuns**.
- Até 12 datas de solicitação associadas aos pares exclusivos da API,
  com contagens agregadas, sem revelar OP, código, descrição ou usuário.
- Advertência de que `LastRequest` informa a data da solicitação,
  **não** a data/hora da inclusão no sistema.

A finalidade é distinguir variação temporal de diferenças persistentes.
O próximo teste ideal compara Excel e API com o menor intervalo possível,
registrando o momento de extração e mantendo a quarentena do material
sem código. Nenhuma nova fonte é publicada automaticamente.

## Atualização com ressalvas — política operacional

Inconsistências **isoladas de registro** identificadas no JSON MES não devem
interromper o processamento de materiais válidos. A rotina de homologação
passa a calcular a política `PROCESSAR`, `PROCESSAR_COM_RESSALVAS` ou
`PROTEGER_BASE` separadamente da comparação histórica com o Excel.

- `PROCESSAR_COM_RESSALVAS`: registros válidos seguem elegíveis;
  os inválidos ficam identificados para quarentena e correção.
- `PROTEGER_BASE`: nenhum material válido, contagens inconsistentes,
  mais de 0,5% dos registros com inconsistência ou menos de 80% do
  volume total da referência. É um limite inicial conservador, sujeito
  a calibração operacional. Mantém-se a última base válida.
- `PROCESSAR`: recebimento estruturalmente íntegro.

A diferença entre a API corrente e um Excel extraído anteriormente não
é, isoladamente, erro de material: pode refletir movimentações posteriores.
A quarentena do Conversor MRP já é publicada separadamente quando sua
rotina de processamento é acionada.

**Limite importante:** este ajuste prepara a regra de continuidade e
sinaliza a situação na homologação. O Monitor não envia dados à Central;
a coleta/persistência automática da API ainda depende de uma etapa de
integração dedicada e configuração segura do ambiente executor.
