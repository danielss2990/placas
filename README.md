# Placas — reconhecimento de placas, débitos e pagamentos

Aplicação **web e mobile** (PWA instalável no celular) para:

1. **Reconhecer placas veiculares** brasileiras (padrão antigo `ABC-1234` e Mercosul `ABC1D23`) a partir de foto ou da câmera, usando **Python + OpenCV** para localizar a placa e **Tesseract OCR** para ler os caracteres;
2. **Calcular o débito atualizado** de cada veículo (IPVA, licenciamento, multas, estacionamento, pedágio…) com multa de mora, juros e descontos;
3. **Gerenciar formas de pagamento**: PIX (com BR Code "copia e cola"), boleto, cartão de débito, cartão de crédito parcelado e dinheiro — com confirmação, cancelamento e estorno.

## Como executar

Requisitos: Python 3.10+ e o binário do **Tesseract**.

```bash
# Ubuntu/Debian:  sudo apt install tesseract-ocr
# macOS:          brew install tesseract
# Windows:        https://github.com/UB-Mannheim/tesseract/wiki (adicione ao PATH)

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py                       # http://localhost:5000
```

Ou com Docker (já instala o Tesseract):

```bash
docker build -t placas . && docker run -p 5000:5000 placas
```

Na primeira execução o banco SQLite (`instance/placas.db`) é criado com 3 veículos de demonstração
(`BRA2E19`, `ABC1234`, `RIO4F56`). Para desativar: `SEED_DEMO_DATA=0`.

Para gerar uma foto de teste: `python scripts/make_sample.py BRA2E19 carro.jpg`.

### No celular

A interface é um **PWA** responsivo: abra o endereço do servidor no navegador do celular e use
**"Adicionar à tela inicial"** para instalá-lo como app (ícone próprio, tela cheia, funciona offline para a interface).

- **Foto / galeria** abre a câmera nativa do celular e funciona em HTTP.
- **Câmera ao vivo** (pré-visualização no app) exige HTTPS fora do `localhost`:
  `pip install cryptography && python run.py --https` (certificado autoassinado) ou publique atrás de um proxy com TLS.

## Como funciona o reconhecimento

`app/recognition/`

| Etapa | Arquivo | Técnica (OpenCV) |
|---|---|---|
| Localização | `detector.py` | (a) bordas Canny + contornos com 4 vértices e proporção de placa, com correção de perspectiva; (b) morfologia black-hat/top-hat + gradiente Sobel + fechamento para achar blocos de texto |
| Pré-processamento | `detector.py` | redimensionamento, CLAHE, Otsu e limiar adaptativo; segmentação dos caracteres por componentes conectados para recortar só a faixa dos 7 caracteres (remove moldura e faixa "BRASIL") |
| OCR | `recognizer.py` | Tesseract (`--psm 7`/`6`, whitelist A–Z0–9); o motor é injetável (EasyOCR, modelo próprio…) |
| Pós-processamento | `plate_format.py` | correção por posição (ex.: `0→O` onde deve haver letra, `B→8` onde deve haver número), validação dos formatos antigo/Mercosul, busca da equivalência `ABC1234 ↔ ABC1C34` |

O resultado traz a placa, confiança heurística, recorte da placa e a imagem anotada. O usuário pode corrigir a leitura manualmente antes de consultar.

> Os testes automatizados usam imagens sintéticas. Em fotos reais a taxa de acerto depende de ângulo, distância,
> iluminação e reflexos; para produção recomenda-se avaliar com um conjunto de fotos reais e, se necessário,
> trocar o motor de OCR/detector por um modelo treinado (ex.: YOLO + OCR) — basta passar outro `ocr_engine`.

## Regras de cálculo do débito

`app/services/debts.py` (configuráveis em `DebtRules`). Valores em centavos, arredondamento meio-para-cima.

| Componente | Regra padrão |
|---|---|
| Multa de mora | 0,33% ao dia de atraso, limitada a 20% do principal |
| Juros de mora | 1% ao mês **ou fração** de atraso (juros simples) |
| Desconto | pagamento até o vencimento: 20% em multas de trânsito, 3% no IPVA |

Exemplo: R$ 100,00 vencido em 10/01, pago em 14/02 → 35 dias (multa 11,55% = R$ 11,55) + 2 meses (juros R$ 2,00) = **R$ 113,55**.

A data de cálculo pode ser simulada: `GET /api/vehicles/ABC1234/debts?date=2026-12-31`.

## Formas de pagamento

`app/services/payments.py`

| Meio | Tarifa | Parcelas | Confirmação |
|---|---|---|---|
| PIX | — | 1x | pendente até confirmação (expira em 30 min); gera BR Code EMV com CRC16 |
| Boleto | R$ 2,50 | 1x | pendente até compensação (expira em 3 dias) |
| Cartão de débito | — | 1x | imediata |
| Cartão de crédito | — | até 12x (3x sem juros; 4x–12x a 1,99% a.m., Tabela Price) | imediata |
| Dinheiro | — | 1x | imediata |

Um débito incluído em um pagamento pendente fica reservado (não pode entrar em outro pagamento). Cancelar ou
expirar o pagamento libera o débito; estornar um pagamento aprovado reabre os débitos.

> **Gateway simulado.** Cartões são aprovados automaticamente e PIX/boleto são confirmados pelo botão
> "Confirmar recebimento" (que faz o papel do webhook do banco). Para produção, implemente
> `_gateway_authorize` e um webhook com o seu PSP; dados de cartão nunca devem trafegar por este servidor
> (use a tokenização do PSP). Configure o recebedor PIX com `PIX_KEY`, `PIX_MERCHANT_NAME`, `PIX_MERCHANT_CITY`.

## API REST

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` | status e disponibilidade do OCR |
| POST | `/api/recognize` | imagem (multipart `image` ou JSON base64) → placa + veículo + débitos |
| GET | `/api/recognitions` | histórico de leituras |
| GET/POST | `/api/vehicles` | listar (`?q=`) / cadastrar |
| GET/PUT/DELETE | `/api/vehicles/<placa>` | detalhe com débitos calculados / editar / excluir |
| GET/POST | `/api/vehicles/<placa>/debts` | débitos atualizados (`?date=`) / lançar débito |
| DELETE | `/api/debts/<id>` | cancelar débito |
| GET | `/api/payment-methods` | formas de pagamento |
| POST | `/api/vehicles/<placa>/payments/simulate` | todas as opções e parcelas para os débitos selecionados |
| POST | `/api/vehicles/<placa>/payments` | criar pagamento `{debt_ids, method, installments}` |
| GET | `/api/payments` | listar (`?status=`, `?plate=`) |
| POST | `/api/payments/<id>/confirm` · `/cancel` · `/refund` | confirmar, cancelar, estornar |
| GET | `/api/stats` | indicadores do painel |

## Testes

```bash
pytest
```

Cobrem formato/correção de placas, cálculo de débitos, parcelamento e PIX, fluxos da API e o reconhecimento
OpenCV+Tesseract em imagens sintéticas (estes são ignorados se o Tesseract não estiver instalado).

## Estrutura

```
app/
  recognition/   detector.py (OpenCV), recognizer.py (OCR), plate_format.py (regras BR)
  services/      debts.py (cálculo), payments.py (meios de pagamento, PIX)
  models.py      Vehicle, Debt, Payment, PaymentItem, RecognitionLog (SQLAlchemy)
  api.py         API REST
  templates/ static/   interface web/PWA (HTML, CSS, JS puro, service worker, manifest)
scripts/make_sample.py  gera imagens sintéticas de veículos
tests/
```

## Próximos passos sugeridos

- Autenticação/perfis de usuário (operador, administrador) antes de expor o sistema;
- Integração real com PSP (PIX dinâmico/webhooks, adquirente de cartão, registro de boleto);
- Integração com bases oficiais de débitos (Detran/Sefaz) em vez do cadastro manual;
- Empacotar o PWA como app nativo (Capacitor/TWA) se for necessário publicar nas lojas.
