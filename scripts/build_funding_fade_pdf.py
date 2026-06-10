"""Generate a one-off PDF explaining how Funding Fade works in this repo."""
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "funding_fade_explicacao.pdf"


def build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            spaceAfter=4,
            textColor=HexColor("#111111"),
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=10,
            leading=13,
            textColor=HexColor("#666666"),
            spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=16,
            textColor=HexColor("#0A3C78"),
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=HexColor("#1A1A1A"),
            spaceAfter=6,
            alignment=TA_LEFT,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            leftIndent=14,
            bulletIndent=2,
            textColor=HexColor("#1A1A1A"),
            spaceAfter=2,
        ),
        "code": ParagraphStyle(
            "code",
            parent=base["Code"],
            fontName="Courier",
            fontSize=9.5,
            leading=13,
            backColor=HexColor("#F4F4F4"),
            borderPadding=6,
            leftIndent=4,
            rightIndent=4,
            textColor=HexColor("#222222"),
            spaceBefore=2,
            spaceAfter=8,
        ),
    }


def build_story(styles: dict) -> list:
    s = styles
    story: list = []

    story.append(Paragraph("Funding Fade — Como funciona", s["title"]))
    story.append(
        Paragraph(
            "Estratégia do repositório <b>Master-Trader</b> · FundingFadeV1 / FundingShortV1",
            s["subtitle"],
        )
    )

    story.append(
        Paragraph(
            "Este documento explica de forma direta como a estratégia Funding Fade funciona "
            "no repositório Master-Trader. O foco é operacional: o que dispara o sinal, quais "
            "filtros existem, como o bot sai e por que isso dá dinheiro.",
            s["body"],
        )
    )

    story.append(Paragraph("1. Ideia central", s["h2"]))
    story.append(
        Paragraph(
            "Em perpétuos (ex: Binance Futures) existe a <b>funding rate</b>: a cada 8 horas, "
            "longs pagam shorts ou vice-versa, dependendo de quem está mais aglomerado. "
            "Funding muito negativa significa muita gente short alavancado pagando os longs. "
            "Funding muito positiva significa muito long alavancado pagando os shorts. "
            "Quando a funding fica em extremo, o posicionamento está aglomerado, e isso "
            "tende a virar (squeeze). O Funding Fade aposta nessa <b>reversão</b> — não no "
            "carry da funding em si.",
            s["body"],
        )
    )

    story.append(Paragraph("2. O sinal", s["h2"]))
    story.append(
        Paragraph(
            "O bot não olha gráfico. Ele calcula, por par, a média e o desvio padrão da "
            "funding nos últimos 500 períodos (cerca de 167 dias com funding de 8h) e "
            "compara com a funding atual.",
            s["body"],
        )
    )
    story.append(
        Paragraph(
            "long&nbsp;&nbsp;quando&nbsp;&nbsp;funding &lt; média_500 − 1 × desvio_padrão<br/>"
            "short&nbsp;quando&nbsp;&nbsp;funding &gt; média_500 + 1 × desvio_padrão",
            s["code"],
        )
    )
    story.append(
        Paragraph(
            "<b>FundingFadeV1.py</b> opera o lado long. <b>FundingShortV1.py</b> é o "
            "espelho para o lado short.",
            s["body"],
        )
    )

    story.append(Paragraph("3. Filtros de confirmação (entrada)", s["h2"]))
    story.append(
        Paragraph("O sinal de funding sozinho não basta. Para abrir, também precisa:", s["body"])
    )
    for txt in [
        "<b>ADX(14) &gt; 25</b> — mercado em tendência, evita lateralização",
        "<b>Volume &gt; 1,5× média de 20 períodos</b> — liquidez confirmando",
        "<b>Macro gate (long)</b>: BTC acima da SMA50 e SMA200. "
        "<b>Macro gate (short)</b>: BTC fraco — abaixo da SMA50 ou RSI &lt; 40.",
    ]:
        story.append(Paragraph(txt, s["bullet"], bulletText="•"))

    story.append(Paragraph("4. Saída", s["h2"]))
    for txt in [
        "<b>ROI escalonado</b>: 8% na entrada, 5% em 6h, 3% em 12h, 2% em 24h",
        "<b>Stoploss</b> fixo em −5%",
        "<b>Sem trailing stop</b> (testado: subtraía retorno em ruído de 1 minuto)",
        "<b>exit_profit_only = True</b> com offset de 1% (só sai com lucro positivo)",
    ]:
        story.append(Paragraph(txt, s["bullet"], bulletText="•"))

    story.append(Paragraph("5. Frequência (\"o tempo todo scanning\")", s["h2"]))
    story.append(
        Paragraph(
            "Candles de <b>1 hora</b>. A cada fechamento de candle, o bot recalcula sinais "
            "em todos os pares e abre/fecha o que precisar. A funding em si só atualiza a "
            "cada 8h (00/08/16 UTC). Um cron baixa as funding rates diariamente e o bot "
            "relê o arquivo automaticamente quando o mtime muda — não precisa reiniciar.",
            s["body"],
        )
    )
    story.append(
        Paragraph(
            "O bot fica 24/7 conectado na VPS, mas a decisão é horária. O \"scanning\" "
            "constante é o WebSocket mantendo o candle vivo — a lógica só roda no "
            "fechamento. Custo de infraestrutura é basicamente VPS + chamadas REST/WS da "
            "Binance. <b>Não tem custo onchain, não gasta token.</b>",
            s["body"],
        )
    )

    story.append(Paragraph("6. Parâmetros usados em produção", s["h2"]))
    rows = [
        ["Timeframe", "1 hora"],
        ["Janela da funding", "500 períodos (~167 dias)"],
        ["Limite ADX", "25"],
        ["Multiplicador de volume", "1,5× SMA(20)"],
        ["Macro gate (long)", "BTC > SMA50 e BTC > SMA200"],
        ["Macro gate (short)", "BTC < SMA50 ou RSI(BTC) < 40"],
        ["Stoploss", "−5%"],
        ["Trailing stop", "Desligado"],
        ["Exit profit only", "True (offset 1%)"],
        ["Stake por slot", "USD 15"],
        ["Máximo de posições", "2 (long) / até 3 no lab"],
        ["Stale threshold", "alerta se funding > 12h sem atualizar"],
    ]
    table = Table(rows, colWidths=[60 * mm, 100 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 10),
                ("TEXTCOLOR", (0, 0), (-1, -1), HexColor("#1A1A1A")),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [HexColor("#FAFAFA"), HexColor("#FFFFFF")]),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, HexColor("#E0E0E0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("7. Validação (lab)", s["h2"]))
    story.append(Paragraph("<b>FundingFadeV1 (long)</b>, 3,3 anos com detalhe de 1 minuto:", s["body"]))
    for txt in [
        "431 trades · win rate 65,7% · profit factor 1,29",
        "Retorno total +60,66% · drawdown máximo 19,6%",
        "Walk-forward: 6 de 6 janelas rolling lucrativas",
        "Forte em 2024-H2 (chop), inverso ao Keltner — bom diversificador",
    ]:
        story.append(Paragraph(txt, s["bullet"], bulletText="•"))
    story.append(Paragraph("<b>FundingShortV1 (short)</b>, Jul 2025 – Abr 2026:", s["body"]))
    story.append(
        Paragraph(
            "161 trades · profit factor 1,40 · retorno +51,78% · drawdown 14,41%",
            s["bullet"],
            bulletText="•",
        )
    )

    story.append(Paragraph("8. Por que NÃO é carry de funding", s["h2"]))
    story.append(
        Paragraph(
            "Foi testado fazer delta-neutral (long spot + short perp) só para capturar a "
            "funding como carry. Resultado: <b>−33,05%</b> contra <b>+82,29%</b> da versão "
            "direcional. Motivo: o ganho de funding por trade é ~1,1 bps, enquanto o custo "
            "round-trip é ~24 bps. O edge está na <b>reversão de preço</b> que vem depois "
            "da posição aglomerada virar — não na taxa em si. Hedge mata o sinal.",
            s["body"],
        )
    )

    story.append(Paragraph("9. Resumo em uma frase", s["h2"]))
    story.append(
        Paragraph(
            "Quando a funding rate de um perpétuo fica estatisticamente extrema (mais de 1 "
            "desvio padrão da média de 500 períodos), o posicionamento está aglomerado; "
            "com confirmação de ADX, volume e filtro macro do BTC, o bot abre na direção "
            "contrária e sai por ROI ou stop — capturando o squeeze que costuma vir.",
            s["body"],
        )
    )

    return story


def on_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica-Oblique", 8)
    canvas.setFillColor(HexColor("#888888"))
    canvas.drawCentredString(
        A4[0] / 2,
        12 * mm,
        f"Master-Trader / FundingFadeV1 · página {doc.page}",
    )
    canvas.restoreState()


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title="Funding Fade — Como funciona",
        author="Master-Trader",
    )
    styles = build_styles()
    story = build_story(styles)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"PDF gerado em: {OUTPUT}")


if __name__ == "__main__":
    main()
