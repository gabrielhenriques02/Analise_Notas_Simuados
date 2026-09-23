# Análise de Simulados — Turma ITA 2026

Aplicação web (FastAPI + Jinja2 + SQLite) que lê a planilha de correção dos simulados,
exibe as análises na interface e gera relatórios em PDF.

## Regras de negócio — decididas com a coordenação, valem sobre a planilha

- **Aprovação:** `> 4,0` em **cada** matéria **e** `> 5,0` na média de Mat+Fís+Quí.
  A planilha usa `4,16` numa fórmula antiga; **ignorar**. Os dois valores são
  configuráveis (`CORTE_MATERIA`, `CORTE_GERAL`).
- **Inglês** entra no mínimo por matéria, mas **não** entra na média geral.
- **Ausentes são excluídos de toda estatística** e listados à parte como
  `AUSENTE — não realizou a prova`.
- **Faltas** não existem como coluna: são inferidas (prova zerada ou linha ausente) e
  precisam de **confirmação humana** antes de virar registro.
- **Classificação** está vazia no ciclo 5 — sempre calcular, nunca ler da planilha.
- **Gabarito** aceita **múltiplas alternativas corretas** (`A/E`) e o estado
  `ANULADA`, que conta como acerto para todos.
- **Acerto é derivado** de `alternativa_marcada == gabarito`, não importado como 0/1.
- **Lista de revisão exclui as difíceis.** O KPI "QUESTÕES COM ERRO ≥ 50%" e a seção
  de enunciados contam só **fácil e média** com acerto < 50%. O relatório da 2ª fase
  diz explicitamente: "as de nível difícil constam apenas na análise acima". É por
  isso que o Ciclo 5 de Matemática conta 4 e não 5.
- **Alerta** (`CRÍTICA` = fácil, `ATENÇÃO` = média/difícil) vale para todos os níveis;
  não confundir com a lista de revisão.
- **Presença na 2ª fase depende da falta confirmada.** A inferência por prova zerada
  conta a mais: no Ciclo 5 de Matemática ela vê 7 ausentes, o relatório registra 5.
  Quando a coordenação marca a falta como `confirmada=False`, o aluno volta a contar
  e os números batem com o relatório (34 presentes, média 3,05, mediana 2,60).

## Mapeamento das questões (1ª fase, 48 questões)

`MAT = Q1–Q12` · `FÍS = Q13–Q24` · `QUÍ = Q25–Q36` · `ING = Q37–Q48`
Nota por matéria = `acertos × 10/12`. Média geral = `média(MAT, FÍS, QUÍ)`.

2ª fase: 10 questões discursivas por matéria, 0–10 cada. Nota = média das dez.

## Armadilhas da planilha

- Nomes têm 89 grafias para ~41 pessoas. Normalizar (maiúscula, sem acento, espaços
  colapsados) **e** manter tabela de apelidos: `GONCALVES`↔`GONÇAVELS`,
  `ABREU LIMA`↔`ABREU DE LIMA`.
- Linhas fantasma em `CORREÇÃO 2ª 2025` (583–667): filtrar por `NOME` não-vazio.
- `NÍVEL SIMULADOS` tem **duas tabelas independentes** na mesma aba (`A1:L19` e `N2:BJ8`),
  com vocabulários diferentes: `MÉDIO` na 2ª fase, `MÉDIA` na 1ª. Normalizar.
- `RM` em `CORREÇÃO REDAÇÃO` mistura número e string com TAB (`"\t0383083"`).
- Arredondar na leitura: o arquivo guarda ruído de float (`5.0999999999999996`).

## Recortes das questões (app/provas/)

- **Margens são medidas por documento, nunca fixas.** O logo do cabeçalho termina em
  y≈46 na prova de Física, y≈71 em Matemática e Química, y≈75 na 1ª fase. Uma
  constante única erra dos dois lados: 62 descartava as questões 5 e 8 de Física,
  40 fazia o recorte da 1ª fase engolir o logo.
- **`get_pixmap(clip=...)` devolve o pedaço posicionado nas coordenadas da página**
  e `copy()` só copia a interseção. Sempre `set_origin(0, topo)` antes de empilhar,
  senão um recorte do pé da página sai em branco — com o arquivo do tamanho certo.
- **Texto de apoio tem duas redações**: "As questões 37 a 40 referem-se ao texto a
  seguir" e "Leia o texto a seguir para responder às questões de 01 a 03". A folha
  de constantes não cita questão nenhuma e vale para a prova inteira.
- **Nunca exibir texto extraído em exatas.** A matemática vem do OMML do Word em
  linhas de base separadas e sai como `cosx3ya.cos³y−=`. A imagem é a única forma
  fiel. Expoentes ficam ACIMA da linha do marcador `Questão n.` — o limite entre
  questões precisa recuar até o topo visual do bloco, incluindo desenhos.
- Numeração: o PDF da 1ª fase traz 1–48 e a prova no banco traz 1–12 por matéria;
  `Prova.offset_numeracao` faz a ponte (Física 12, Química 24, Inglês 36).

## Relatórios em PDF (app/reports/, app/charts/)

- A4 paisagem (841,89 × 595,27), como os originais. Corpo em 7–8pt no lugar dos 5–6pt.
- **Fonte:** DejaVu. A Inter está instalada mas só em `.otf` com contornos PostScript,
  que o ReportLab não lê. A DejaVu cobre `≥ ≤ − º · —`.
- **Carimbar o rodapé com Helvetica base-14 troca `—` por `·` em silêncio.** O total
  de páginas só é conhecido no fim, então o rodapé é carimbado com PyMuPDF — usando
  `fontfile` da DejaVu, nunca `fontname="helv"`.
- **Recortes a 150 dpi:** um ponto do PDF vale 150/72 px. Abaixo de 45% do tamanho
  natural o enunciado de 10pt cai para menos de 4,5pt e some. Por isso o texto de
  apoio só entra junto quando a escala resultante se mantém acima disso — a folha de
  constantes de Química, sozinha, torna qualquer questão ilegível.
- **Gráficos:** um só gerador SVG (`app/charts/svg.py`) serve a tela e o PDF, este
  via `svglib`, que converte px em pt no fator 0,75 — o passo das barras precisa ser
  dividido por ele para casar com a altura de linha da tabela.
- **Medido com o validador de paleta:** verde `#2e8b57` vs vermelho `#c83434` dá ΔE
  5,1 em deuteranopia, abaixo do piso de 6 — indistinguíveis. O par realmente usado
  na grade (verde sólido vs `#f8e5e5`) dá 33,6, e ainda assim as células levam ✓/✗.
  Nunca remover o glifo.

## Privacidade — o repositório é PÚBLICO

Nenhum dado de aluno vai para o git. Nunca commitar `.xlsx`, `.pdf`, `.db` nem nada de
`data/`, `planilha_dados/`, `exemplos_relatorios/`, `exemplos_pdf_provas/`.
O hook de `pre-commit` recusa; não contorne com `git add -f`.

## Ambiente

Python 3.14 **sem pip no sistema** e sem Node. Tudo roda dentro de `.venv`, criada por
`scripts/bootstrap.sh` sem `sudo`. Use `.venv/bin/python` e `.venv/bin/pytest`.
Em PyMuPDF, importar `pymupdf` (não `fitz`, que está descontinuado).

## Verificação

Os relatórios em `exemplos_relatorios/` são a referência validada. Qualquer mudança em
`app/analytics/` deve manter estes números:

| Referência | Esperado |
|---|---|
| Ciclo 5 · 1ª Fase · Matemática | média 5,61 · variação +0,90 · 26/30 acima do corte · top5 8,67 · 4 questões com erro ≥ 50% |
| Ciclo 5 · 2ª Fase · Matemática | média 3,05 · mediana 2,60 · 11/34 acima do corte · Q1 4,79/10 → 47,9% |
| Potenciais · Murilo Coser | geral C1 8,61 · regularidade 0,73 (desvio populacional) · fáceis/prova 3,2 |
| Unificado | índice de dificuldade C1 1ª fase 2,06 · média das posições Murilo 70º |

## Convenções

- Interface, mensagens de erro, nomes de tela e commits em **português**.
- Números no padrão brasileiro: vírgula decimal, ordinal `º`, milhar com ponto.
- Código (variáveis, funções, tabelas) em português sem acento: `resultado_prova`,
  `nota_final`, `calcular_media_turma`.
