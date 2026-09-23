# Análise de Simulados — Turma ITA 2026

Aplicação web para acompanhar o desempenho da turma nos simulados, com controle de
acesso por login, análise por ciclo, fase, matéria, frente e questão, e geração de
relatórios em PDF prontos para download.

> **Este repositório não contém dados de alunos.** As planilhas, os relatórios e as
> provas ficam fora do versionamento. Para desenvolver, use a planilha de exemplo em
> `samples/`, que tem a mesma estrutura com nomes fictícios.

## O que faz

- Importa a planilha de correção dos simulados e reconcilia os alunos
- Mostra na interface as mesmas análises dos relatórios usados hoje pela coordenação
- Exibe o enunciado recortado de cada questão ao lado da estatística de acerto da turma
- Gera novos relatórios em PDF e os disponibiliza para download

## Requisitos

Python 3.11 ou superior. Nada mais — sem Node, sem banco externo, sem pacote de sistema.

## Instalação

```bash
scripts/bootstrap.sh     # cria o venv, instala o pip e as dependências, gera o .env
scripts/install-hooks.sh # instala o hook que bloqueia commit de dado de aluno
scripts/run.sh           # sobe em http://127.0.0.1:8000
```

Depois, crie a primeira conta de coordenação:

```bash
.venv/bin/python scripts/criar_admin.py coordenacao@madan.com.br "Coordenação"
```

O comando imprime uma senha inicial. A aplicação se recusa a abrir sessão enquanto a
`SECRET_KEY` do `.env` for a de exemplo — gere a sua com o comando acima.

O `bootstrap.sh` funciona mesmo em sistemas cujo Python não traz `ensurepip` — ele
baixa o `get-pip.py` e instala o pip dentro do ambiente virtual, sem exigir `sudo`.

Depois de criar o `.env`, gere uma chave de sessão própria:

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Perfis de acesso

| Perfil | Alcance |
|---|---|
| Coordenação / admin | Tudo: todas as matérias, importação, relatórios, usuários |
| Professor | Apenas a(s) matéria(s) atribuída(s) |

As contas são criadas pela coordenação dentro da própria interface.

## Estrutura

```
app/          aplicação
  ingest/     leitura e normalização da planilha
  analytics/  métricas e regras de negócio
  provas/     recorte das questões a partir dos PDFs
  charts/     gerador de gráficos SVG (serve a tela e o PDF)
  reports/    geração dos PDFs
samples/      planilha de exemplo com nomes fictícios
tests/        testes automatizados
data/         dados locais — fora do versionamento
```

## Testes

```bash
.venv/bin/pytest
```

Os testes conferem as métricas contra os relatórios de referência já validados pela
coordenação, de modo que qualquer divergência de cálculo aparece como falha.

## Privacidade

O repositório é público. O `.gitignore` bloqueia planilhas, PDFs e bancos de dados, e o
hook de `pre-commit` recusa qualquer commit que os inclua. Antes de publicar, confirme:

```bash
git ls-files | grep -iE '\.(xlsx|pdf|db)$'   # deve sair vazio
```
