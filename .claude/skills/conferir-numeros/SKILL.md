---
description: Confere os números calculados pelo sistema contra os relatórios de referência em exemplos_relatórios. Use ao terminar qualquer mudança em app/analytics/.
allowed-tools: Bash(.venv/bin/pytest *) Bash(.venv/bin/python *)
---

## Estado atual

!`.venv/bin/pytest tests/ -q --tb=line 2>&1 | tail -30`

## Instruções

Compare a saída acima com os valores de referência abaixo. Para cada divergência,
reporte o valor esperado, o calculado e o arquivo de origem do cálculo.

| Referência | Esperado |
|---|---|
| Ciclo 5 · 1ª Fase · Matemática | média 5,61 · variação +0,90 · 26/30 acima do corte · top5 8,67 · maior nota 10,00 · 4 questões com erro >= 50% |
| Ciclo 5 · 1ª Fase · Física | média 3,78 · variação +0,13 · 8 questões com erro >= 50% |
| Ciclo 5 · 2ª Fase · Matemática | média 3,05 · mediana 2,60 · 11/34 acima do corte · top5 6,36 · Q1 4,79/10 -> 47,9% |
| Potenciais · Murilo Coser | geral C1 8,61 · regularidade 0,73 · fáceis/prova 3,2 · 5/5 aprovações |
| Unificado | índice dificuldade C1 1ª fase 2,06 · média das posições Murilo 70º · salto de faltas +190% |

Casos-limite da regra de aprovação que devem continuar valendo:

- Lívia, ciclo 4: `5,83 / 5,00 / 1,67 / 6,67` -> **CORTADO**, corta em QUÍ
- Lucas Emanuel, ciclo 1: geral 5,83 (acima de 5,0) mas `ING 0,83` -> **CORTADO**, corta em ING

Não altere código nesta skill — apenas relate o que diverge.
